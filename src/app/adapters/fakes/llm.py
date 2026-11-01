"""Deterministic FakeLLM adapter for offline agent and guardrail tests."""

from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from app.guardrails.pii_shield import shield
from app.guardrails.validator import call_structured
from app.ports.llm import AgentRole

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class RecordedLLMCall:
    """Record of a single completion call received by FakeLLM."""

    prompt: str
    role: AgentRole
    json_mode: bool


class FakeLLM:
    """Scripted deterministic LLM implementation for fast unit and eval tests."""

    def __init__(
        self,
        scripted_responses: list[str] | None = None,
        role_responses: dict[AgentRole, str] | None = None,
    ) -> None:
        self._queue: list[str] = list(scripted_responses or [])
        self._role_responses: dict[AgentRole, str] = dict(role_responses or {})
        self.calls: list[RecordedLLMCall] = []

    async def complete(
        self,
        prompt: str,
        *,
        role: AgentRole = AgentRole.LIGHTWEIGHT_PARSER,
        json_mode: bool = False,
    ) -> str:
        safe_prompt = shield(prompt)
        self.calls.append(RecordedLLMCall(prompt=safe_prompt, role=role, json_mode=json_mode))
        if self._queue:
            return self._queue.pop(0)
        if role in self._role_responses:
            return self._role_responses[role]
        return '{"status": "ok"}'

    async def complete_structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        role: AgentRole = AgentRole.LIGHTWEIGHT_PARSER,
        retries: int = 2,
    ) -> T:
        return await call_structured(self, prompt, schema, role=role, retries=retries)
