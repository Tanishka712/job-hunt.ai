"""PII and credential redaction shield for prompts and structured logs."""

import logging
import re

_REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Explicit secret tags: [SECRET:...]
    (re.compile(r"\[SECRET:[^\]]+\]", re.IGNORECASE), "[REDACTED_SECRET]"),
    # Groq, OpenAI, GitHub, Slack, AWS, and generic bearer/API tokens
    (
        re.compile(
            r"\b(?:gsk_[A-Za-z0-9]{16,}|sk-(?:proj-)?[A-Za-z0-9_\-]{16,}|"
            r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
            r"xox[baprs]-[A-Za-z0-9\-]{15,}|AKIA[0-9A-Z]{16}|"
            r"tok_live_[A-Za-z0-9_]{12,}|sec_[A-Za-z0-9_]{16,})\b"
        ),
        "[REDACTED_TOKEN]",
    ),
    # Authorization: Bearer <token>
    (
        re.compile(r"(Bearer\s+)(?!\[REDACTED_)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
        r"\1[REDACTED_BEARER]",
    ),
    # Key-value credential assignments (password=..., api_key: ..., AccountKey=...)
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|api_key|apikey|client_secret|access_token|accountkey)"
            r"\s*([:=])\s*(?!\[REDACTED_)(['\"]?)[^\s'\";,]+(\3)"
        ),
        r"\1\2[REDACTED_CREDENTIAL]",
    ),
    # US Social Security Numbers
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    # Email addresses
    (
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    # Phone numbers (international +1-415-555-0192, (212) 555-8473, +91 9876543210)
    (
        re.compile(
            r"(?:(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{2,4}\)[\s.\-]?|\d{3}[\s.\-])\d{3}[\s.\-]?\d{4}"
            r"|\+\d{1,3}[\s.\-]?\d{10})\b"
        ),
        "[REDACTED_PHONE]",
    ),
]


def shield(text: str) -> str:
    """Redact emails, phone numbers, API keys, and credentials from `text`."""
    redacted = text
    for pattern, replacement in _REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def contains_secret(text: str) -> bool:
    """Return True if `text` matches any unredacted PII or credential pattern."""
    return any(pattern.search(text) is not None for pattern, _ in _REDACTION_PATTERNS)


class RedactingLogFilter(logging.Filter):
    """Logging filter that scrubs PII and secrets from log messages and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = shield(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    shield(arg) if isinstance(arg, str) else arg for arg in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: (shield(v) if isinstance(v, str) else v) for k, v in record.args.items()
                }
        return True
