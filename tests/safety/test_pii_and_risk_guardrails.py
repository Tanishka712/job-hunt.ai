"""Safety tests for S2: 20 seeded secret prompts, log redaction, and R3 tool gate."""

import logging

import pytest

from app.guardrails.pii_shield import RedactingLogFilter, contains_secret, shield
from app.guardrails.risk import (
    ApprovalRequiredError,
    ApprovalToken,
    Risk,
    create_approval_token,
    get_registered_tools,
    tool,
)

_FAKE_GSK = "gsk" + "_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789AbCdEf"
_FAKE_SK = "sk-" + "proj-1234567890abcdefghijklmnopqrstuvwx"
_FAKE_GHP = "ghp" + "_0123456789abcdefghijklmnopqrstuvwxyz"
_FAKE_GHPAT = "github" + "_pat_11ABCDEF0123456789_abcdefghijklmnop"
_FAKE_AKIA = "AKIA" + "IOSFODNN7EXAMPLE"
_FAKE_XOXB = "xox" + "b-123456789012-123456789012-abcdefghijklmnopqrstuvwx"
_FAKE_GSK2 = "gsk" + "_11223344556677889900aabbccddeeff"

TWENTY_SEEDED_SECRET_PROMPTS: list[tuple[str, str]] = [
    ("Contact me at alice.smith@example.com for details.", "alice.smith@example.com"),
    ("Reach HR at hr-team+recruiting@acme-corp.io today.", "hr-team+recruiting@acme-corp.io"),
    ("My phone number is +1-415-555-0192, call anytime.", "+1-415-555-0192"),
    ("Direct mobile: (212) 555-8473 ext 4.", "(212) 555-8473"),
    ("Indian mobile: +91 9876543210 for WhatsApp.", "9876543210"),
    (f"Groq key is {_FAKE_GSK}", _FAKE_GSK),
    (f"OpenAI token {_FAKE_SK}", _FAKE_SK),
    (f"GitHub PAT {_FAKE_GHP}", _FAKE_GHP),
    (f"GitHub fine-grained {_FAKE_GHPAT}", _FAKE_GHPAT),
    (
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.sig",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
    ),
    (f"AWS key {_FAKE_AKIA} in config", _FAKE_AKIA),
    (f"Slack token {_FAKE_XOXB}", "123456789012"),
    ("password = 'MySuperSecretPassword123!'", "MySuperSecretPassword123!"),
    ('api_key: "sec_99887766554433221100aabbccddeeff"', "sec_99887766554433221100aabbccddeeff"),
    ("client_secret=topsecretvalue987654321", "topsecretvalue987654321"),
    ("access_token: 'tok_live_abcdef0123456789abcdef'", "tok_live_abcdef0123456789abcdef"),
    ("SSN 123-45-6789 must never leave the host", "123-45-6789"),
    ("Private tagged [SECRET:my_vault_credential_xyz] inside prompt", "my_vault_credential_xyz"),
    (
        "Conn string AccountKey=aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789==;",
        "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789==",
    ),
    (
        f"Secondary email founder@startup.co.uk and key {_FAKE_GSK2}",
        "founder@startup.co.uk",
    ),
]


@pytest.mark.safety
@pytest.mark.parametrize(("raw_prompt", "secret_substring"), TWENTY_SEEDED_SECRET_PROMPTS)
def test_pii_shield_removes_all_20_seeded_secrets(raw_prompt: str, secret_substring: str) -> None:
    """Every seeded PII/credential across 20 sample prompts must be redacted by shield()."""
    redacted = shield(raw_prompt)
    assert secret_substring not in redacted
    assert not contains_secret(redacted)


@pytest.mark.safety
def test_logs_contain_no_secrets(caplog: pytest.LogCaptureFixture) -> None:
    """Grep test on captured logs confirming RedactingLogFilter strips secrets and emails."""
    logger = logging.getLogger("mint.llm.test")
    logger.addFilter(RedactingLogFilter())

    secret_key = "gsk" + "_SecretGroqKeyForLogTest1234567890ABCDEF"
    secret_email = "candidate.private@example.org"
    with caplog.at_level(logging.INFO, logger="mint.llm.test"):
        logger.info("Sending request for %s with key %s", secret_email, secret_key)

    combined_logs = "\n".join(caplog.messages)
    assert secret_key not in combined_logs
    assert secret_email not in combined_logs
    assert "[REDACTED" in combined_logs


@tool("test_r1_reader", risk=Risk.R1_READ_EXTERNAL)
async def _sample_r1_tool(url: str) -> str:
    return f"fetched:{url}"


@tool("test_r3_submitter", risk=Risk.R3_SIDE_EFFECT)
async def _sample_r3_tool(job_id: str) -> str:
    return f"submitted:{job_id}"


@pytest.mark.safety
async def test_r3_tools_blocked_without_valid_approval() -> None:
    """Every registered R3 tool must raise ApprovalRequiredError without a valid token."""
    # R1 tool runs without approval token
    assert await _sample_r1_tool("https://example.com") == "fetched:https://example.com"

    # R3 tool without token -> raises
    with pytest.raises(ApprovalRequiredError):
        await _sample_r3_tool("job-42")

    # R3 tool with forged HMAC signature -> raises
    forged = ApprovalToken(
        user_id="user-1",
        job_id="job-42",
        contact_id="c-1",
        resume_version=1,
        email_version=1,
        tool_name="test_r3_submitter",
        nonce="nonce-1",
        hmac_signature="forged-hex-signature",
    )
    with pytest.raises(ApprovalRequiredError):
        await _sample_r3_tool("job-42", approval=forged)

    # R3 tool with valid signed token for wrong tool_name -> raises
    wrong_tool_token = create_approval_token(
        secret_key="test-hmac-secret",
        user_id="user-1",
        job_id="job-42",
        contact_id="c-1",
        resume_version=1,
        email_version=1,
        tool_name="other_r3_tool",
        nonce="nonce-2",
    )
    with pytest.raises(ApprovalRequiredError):
        await _sample_r3_tool("job-42", approval=wrong_tool_token)

    # R3 tool with valid signed token -> succeeds
    valid_token = create_approval_token(
        secret_key="test-hmac-secret",
        user_id="user-1",
        job_id="job-42",
        contact_id="c-1",
        resume_version=1,
        email_version=1,
        tool_name="test_r3_submitter",
        nonce="nonce-3",
    )
    result = await _sample_r3_tool(
        "job-42", approval=valid_token, approval_secret="test-hmac-secret"
    )
    assert result == "submitted:job-42"

    # Enumerate all registered R3 tools and confirm none run unapproved
    for name, fn in get_registered_tools().items():
        if fn.risk is Risk.R3_SIDE_EFFECT:
            with pytest.raises(ApprovalRequiredError):
                await fn("job-42")
            assert name == fn.tool_name
