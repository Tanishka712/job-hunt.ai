"""Groq multi-model LLM adapter with per-user BYOK and explicit rate-limit errors for UI."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.guardrails.pii_shield import RedactingLogFilter, shield
from app.guardrails.validator import call_structured
from app.ports.llm import ROLE_MODEL_ROUTES, AgentRole, ModelRoute

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger("mint.llm.groq")
logger.addFilter(RedactingLogFilter())

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


@dataclass(frozen=True)
class GroqTransportResponse:
    """Normalized HTTP response from Groq chat completions endpoint."""

    status_code: int
    content: str
    remaining_tokens: int | None = None
    remaining_requests: int | None = None
    retry_after_seconds: int | None = None
    tokens_used: int = 0


GroqTransportFn = Callable[[str, str, list[dict[str, Any]], bool], Awaitable[GroqTransportResponse]]


def _parse_int_header(headers: httpx.Headers, name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


async def default_httpx_groq_transport(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    json_mode: bool,
) -> GroqTransportResponse:
    """Send chat completion request to Groq OpenAI-compatible endpoint via httpx."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(GROQ_CHAT_COMPLETIONS_URL, json=payload, headers=headers)

    rem_tok = _parse_int_header(resp.headers, "x-ratelimit-remaining-tokens")
    rem_req = _parse_int_header(resp.headers, "x-ratelimit-remaining-requests")
    retry_after = _parse_int_header(resp.headers, "retry-after")

    if resp.status_code != 200:
        return GroqTransportResponse(
            status_code=resp.status_code,
            content=resp.text,
            remaining_tokens=rem_tok,
            remaining_requests=rem_req,
            retry_after_seconds=retry_after,
        )

    body = resp.json()
    content: str = body["choices"][0]["message"]["content"]
    total_tokens: int = int(body.get("usage", {}).get("total_tokens", 0))
    return GroqTransportResponse(
        status_code=200,
        content=content,
        remaining_tokens=rem_tok,
        remaining_requests=rem_req,
        tokens_used=total_tokens,
    )


class GroqAdapterError(RuntimeError):
    """Base error for Groq LLM gateway failures."""


class MissingAPIKeyError(GroqAdapterError):
    """Raised when neither a per-user BYOK key nor a default GROQ_API_KEY is provided."""

    def __init__(self) -> None:
        self.ui_action = "CHANGE_API_KEY"
        super().__init__(
            "No Groq API key configured. Please add or change your Groq API key in settings."
        )


class RateLimitExceededError(GroqAdapterError):
    """Raised when Groq returns 429 so the UI can prompt the user to change their API key."""

    def __init__(
        self,
        *,
        role: AgentRole,
        model: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.role = role
        self.model = model
        self.retry_after_seconds = retry_after_seconds
        self.ui_action = "CHANGE_API_KEY"
        wait_hint = (
            f" (retry after {retry_after_seconds}s)" if retry_after_seconds is not None else ""
        )
        super().__init__(
            f"Groq rate limit reached for model '{model}' (role '{role.value}'){wait_hint}. "
            f"Please enter or change your Groq API key (BYOK) in settings, or wait and retry."
        )


class GroqAdapter:
    """Guarded Groq LLMClient supporting per-user BYOK and explicit rate-limit UI errors."""

    def __init__(
        self,
        default_api_key: str = "",
        *,
        routes: dict[AgentRole, ModelRoute] | None = None,
        transport: GroqTransportFn | None = None,
    ) -> None:
        self._default_api_key = default_api_key.strip()
        self._routes = dict(ROLE_MODEL_ROUTES)
        if routes:
            self._routes.update(routes)
        self._transport = transport or default_httpx_groq_transport

    def _resolve_api_key(self, user_api_key: str | None) -> str:
        if user_api_key and user_api_key.strip():
            return user_api_key.strip()
        if self._default_api_key:
            return self._default_api_key
        raise MissingAPIKeyError()

    async def complete(
        self,
        prompt: str,
        *,
        role: AgentRole = AgentRole.LIGHTWEIGHT_PARSER,
        json_mode: bool = False,
        user_api_key: str | None = None,
    ) -> str:
        api_key = self._resolve_api_key(user_api_key)
        safe_prompt = shield(prompt)
        route = self._routes[role]
        messages = [{"role": "user", "content": safe_prompt}]

        models_to_try = [route.primary, route.fallback]
        saw_rate_limit = False
        last_retry_after: int | None = None
        last_status = 0
        last_body = ""

        for model in models_to_try:
            logger.info("Dispatching role=%s to model=%s", role.value, model)
            resp = await self._transport(api_key, model, messages, json_mode)
            if resp.status_code == 200:
                return resp.content

            last_status = resp.status_code
            last_body = shield(resp.content[:300])
            if resp.status_code == 429:
                saw_rate_limit = True
                last_retry_after = resp.retry_after_seconds

        if saw_rate_limit:
            raise RateLimitExceededError(
                role=role,
                model=route.primary,
                retry_after_seconds=last_retry_after,
            )

        raise GroqAdapterError(
            f"Groq request failed for role '{role.value}' "
            f"(last_status={last_status}, body={last_body})"
        )

    async def complete_structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        role: AgentRole = AgentRole.LIGHTWEIGHT_PARSER,
        retries: int = 2,
        user_api_key: str | None = None,
    ) -> T:
        if user_api_key and user_api_key.strip():
            scoped = GroqAdapter(
                default_api_key=user_api_key.strip(),
                routes=self._routes,
                transport=self._transport,
            )
            return await call_structured(scoped, prompt, schema, role=role, retries=retries)
        return await call_structured(self, prompt, schema, role=role, retries=retries)
