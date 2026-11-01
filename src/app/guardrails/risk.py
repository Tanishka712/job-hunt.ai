"""Risk-tagged tool decorator and cryptographic ApprovalToken gate for R3 tools."""

import functools
import hashlib
import hmac
from collections.abc import Awaitable, Callable
from enum import IntEnum
from typing import Any

from pydantic import BaseModel


class Risk(IntEnum):
    """MINT risk ladder levels for tools."""

    R0_PURE_LOGIC = 0
    R1_READ_EXTERNAL = 1
    R2_WRITE_INTERNAL = 2
    R3_SIDE_EFFECT = 3


class ApprovalRequiredError(PermissionError):
    """Raised when an R3 tool is invoked without a valid, HMAC-verified ApprovalToken."""


class ApprovalToken(BaseModel):
    """Cryptographically signed human approval token required by all R3 tools."""

    user_id: str
    job_id: str
    contact_id: str
    resume_version: int
    email_version: int
    tool_name: str
    nonce: str
    hmac_signature: str


def _canonical_payload(
    *,
    user_id: str,
    job_id: str,
    contact_id: str,
    resume_version: int,
    email_version: int,
    tool_name: str,
    nonce: str,
) -> bytes:
    raw = f"{user_id}:{job_id}:{contact_id}:v{resume_version}:v{email_version}:{tool_name}:{nonce}"
    return raw.encode("utf-8")


def create_approval_token(
    *,
    secret_key: str,
    user_id: str,
    job_id: str,
    contact_id: str,
    resume_version: int,
    email_version: int,
    tool_name: str,
    nonce: str,
) -> ApprovalToken:
    """Create an HMAC-SHA256 signed ApprovalToken for a specific versioned artifact set."""
    msg = _canonical_payload(
        user_id=user_id,
        job_id=job_id,
        contact_id=contact_id,
        resume_version=resume_version,
        email_version=email_version,
        tool_name=tool_name,
        nonce=nonce,
    )
    sig = hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return ApprovalToken(
        user_id=user_id,
        job_id=job_id,
        contact_id=contact_id,
        resume_version=resume_version,
        email_version=email_version,
        tool_name=tool_name,
        nonce=nonce,
        hmac_signature=sig,
    )


def require_valid_approval(
    token: ApprovalToken | None,
    expected_tool_name: str,
    secret_key: str = "default-dev-approval-secret",
) -> None:
    """Verify `token` is present, matches `expected_tool_name`, and has a valid HMAC."""
    if token is None:
        raise ApprovalRequiredError(
            f"R3 tool '{expected_tool_name}' blocked: missing ApprovalToken"
        )
    if token.tool_name != expected_tool_name:
        raise ApprovalRequiredError(
            f"R3 tool '{expected_tool_name}' blocked: token signed for '{token.tool_name}'"
        )

    expected_msg = _canonical_payload(
        user_id=token.user_id,
        job_id=token.job_id,
        contact_id=token.contact_id,
        resume_version=token.resume_version,
        email_version=token.email_version,
        tool_name=token.tool_name,
        nonce=token.nonce,
    )
    expected_sig = hmac.new(secret_key.encode("utf-8"), expected_msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(token.hmac_signature, expected_sig):
        raise ApprovalRequiredError(
            f"R3 tool '{expected_tool_name}' blocked: invalid HMAC signature"
        )


_REGISTERED_TOOLS: dict[str, Any] = {}


def get_registered_tools() -> dict[str, Any]:
    """Return registry of all `@tool`-decorated functions for safety audits."""
    return dict(_REGISTERED_TOOLS)


def tool(name: str, *, risk: Risk) -> Callable[[Callable[..., Awaitable[Any]]], Any]:
    """Decorate an async tool with its MINT risk level and enforce R3 approval gates."""

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Any:
        @functools.wraps(fn)
        async def wrapper(
            *args: Any,
            approval: ApprovalToken | None = None,
            approval_secret: str = "default-dev-approval-secret",
            **kwargs: Any,
        ) -> Any:
            if risk is Risk.R3_SIDE_EFFECT:
                require_valid_approval(approval, name, secret_key=approval_secret)
            return await fn(*args, **kwargs)

        wrapper.risk = risk  # type: ignore[attr-defined]
        wrapper.tool_name = name  # type: ignore[attr-defined]
        _REGISTERED_TOOLS[name] = wrapper
        return wrapper

    return decorator
