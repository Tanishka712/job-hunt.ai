"""Unit tests for the MINT interactive CLI (`src/app/cli.py`)."""

import pytest

from app.adapters.fakes.llm import FakeLLM
from app.adapters.llm.groq_adapter import (
    GroqAdapter,
    GroqTransportResponse,
)
from app.cli import async_main
from app.ports.llm import AgentRole


@pytest.mark.unit
async def test_cli_roles_and_shield_commands(capsys: pytest.CaptureFixture[str]) -> None:
    """`roles` prints model table; `shield` redacts PII and secrets."""
    code = await async_main(["roles"])
    assert code == 0
    out = capsys.readouterr().out
    assert "lightweight_parser" in out
    assert "openai/gpt-oss-120b" in out

    code = await async_main(["shield", "Email me at secret.user@example.com"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Had secret/PII : True" in out
    assert "[REDACTED_EMAIL]" in out
    assert "secret.user@example.com" not in out


@pytest.mark.unit
async def test_cli_prompt_and_extract_commands(capsys: pytest.CaptureFixture[str]) -> None:
    """`prompt` and `extract` route through shield + LLMClient and format output."""
    fake_llm = FakeLLM(
        scripted_responses=[
            "Hello from fake LLM!",
            (
                '{"title": "AI Engineer", "company": "Acme", '
                '"location": "Remote", "required_skills": ["Python", "LangGraph"], '
                '"summary": "Build multi-agent systems"}'
            ),
        ]
    )

    code = await async_main(
        ["prompt", "Hi from user@example.com", "--role", "analytical_reasoner"],
        llm_override=fake_llm,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "[REDACTED_EMAIL]" in out
    assert "Hello from fake LLM!" in out
    assert fake_llm.calls[0].role is AgentRole.ANALYTICAL_REASONER

    code = await async_main(
        ["extract", "Acme is hiring an AI Engineer with Python and LangGraph."],
        llm_override=fake_llm,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert '"company": "Acme"' in out
    assert '"LangGraph"' in out


@pytest.mark.unit
async def test_cli_surfaces_rate_limit_ui_action(capsys: pytest.CaptureFixture[str]) -> None:
    """When rate limits are hit, CLI prints `[UI Action: CHANGE_API_KEY]` and exits with code 2."""

    async def rate_limited_transport(
        api_key: str, model: str, messages: list[dict[str, object]], json_mode: bool
    ) -> GroqTransportResponse:
        return GroqTransportResponse(status_code=429, content="Rate limit", retry_after_seconds=30)

    adapter = GroqAdapter(default_api_key="test-key", transport=rate_limited_transport)
    code = await async_main(["prompt", "Test rate limit"], llm_override=adapter)
    assert code == 2
    err = capsys.readouterr().err
    assert "[UI Action: CHANGE_API_KEY]" in err
