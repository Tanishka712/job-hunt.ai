"""Deterministic FakeLLM adapter for offline agent and guardrail tests."""

from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from app.guardrails.pii_shield import shield
from app.guardrails.validator import call_structured
from app.ports.llm import AgentRole, get_role_system_prompt

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class RecordedLLMCall:
    """Record of a single completion call received by FakeLLM."""

    prompt: str
    system_prompt: str
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
        system_prompt: str | None = None,
        user_api_key: str | None = None,
    ) -> str:
        _ = user_api_key
        safe_prompt = shield(prompt)
        resolved_sys = shield(get_role_system_prompt(role, system_prompt))
        self.calls.append(
            RecordedLLMCall(
                prompt=safe_prompt,
                system_prompt=resolved_sys,
                role=role,
                json_mode=json_mode,
            )
        )
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
        system_prompt: str | None = None,
        user_api_key: str | None = None,
    ) -> T:
        _ = user_api_key
        return await call_structured(
            self,
            prompt,
            schema,
            role=role,
            retries=retries,
            system_prompt=system_prompt,
        )
