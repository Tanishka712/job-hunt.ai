"""Deterministic Pydantic structured output validator with retry feedback."""

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.guardrails.pii_shield import shield
from app.ports.llm import AgentRole, LLMClient

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """Raised when an LLM fails to produce valid structured JSON after max retries."""

    def __init__(
        self, schema: type[BaseModel], attempts: int, last_error: Exception | None
    ) -> None:
        self.schema = schema
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Failed to validate {schema.__name__} after {attempts} attempts: {last_error}"
        )


def _extract_json_object(raw: str) -> str:
    """Strip markdown code fences if the model wrapped its JSON output."""
    cleaned = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence_match:
        return fence_match.group(1)
    return cleaned


async def call_structured(
    llm: LLMClient,
    prompt: str,
    schema: type[T],
    *,
    role: AgentRole = AgentRole.LIGHTWEIGHT_PARSER,
    retries: int = 2,
    system_prompt: str | None = None,
) -> T:
    """Shield `prompt`, call `llm`, and validate against `schema` with at most `retries` retries."""
    safe_base_prompt = shield(prompt)
    schema_json = json.dumps(schema.model_json_schema(), separators=(",", ":"))
    required_keys = list(schema.model_fields.keys())
    current_prompt = (
        f"{safe_base_prompt}\n\n"
        f"Return a single JSON instance with keys {required_keys} matching this schema "
        f"(do NOT return the schema definition itself): {schema_json}"
    )

    last_err: Exception | None = None
    total_attempts = retries + 1

    for attempt in range(1, total_attempts + 1):
        raw = await llm.complete(
            current_prompt,
            role=role,
            json_mode=True,
            system_prompt=system_prompt,
        )
        candidate = _extract_json_object(raw)
        try:
            return schema.model_validate_json(candidate)
        except ValidationError as exc:
            last_err = exc
            error_summary = shield(str(exc))
            current_prompt = (
                f"{safe_base_prompt}\n\n"
                f"Return a single JSON instance with keys {required_keys} matching this schema "
                f"(do NOT return the schema definition itself): {schema_json}\n"
                f"Validation error on attempt {attempt}: {error_summary}\n"
                f"Fix the JSON and return only the corrected JSON object."
            )

    raise StructuredOutputError(schema, total_attempts, last_err)
