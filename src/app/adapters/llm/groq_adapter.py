"""Groq multi-model LLM adapter with automatic key rotation and model fallback."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.adapters.llm.key_pool import GroqKeyPool
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
    tokens_used: int = 0


GroqTransportFn = Callable[[str, str, list[dict[str, Any]], bool], Awaitable[GroqTransportResponse]]


def _parse_int_header(headers: httpx.Headers, name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
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

    if resp.status_code != 200:
        return GroqTransportResponse(
            status_code=resp.status_code,
            content=resp.text,
            remaining_tokens=rem_tok,
            remaining_requests=rem_req,
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
    """Raised when both primary and fallback models fail across available Groq keys."""


class GroqAdapter:
    """Guarded Groq LLMClient routing each AgentRole to its dedicated model family."""

    def __init__(
        self,
        key_pool: GroqKeyPool,
        *,
        routes: dict[AgentRole, ModelRoute] | None = None,
        transport: GroqTransportFn | None = None,
    ) -> None:
        self._key_pool = key_pool
        self._routes = dict(ROLE_MODEL_ROUTES)
        if routes:
            self._routes.update(routes)
        self._transport = transport or default_httpx_groq_transport

    async def complete(
        self,
        prompt: str,
        *,
        role: AgentRole = AgentRole.LIGHTWEIGHT_PARSER,
        json_mode: bool = False,
        user_api_key: str | None = None,
    ) -> str:
        safe_prompt = shield(prompt)
        route = self._routes[role]
        messages = [{"role": "user", "content": safe_prompt}]

        # Try primary model across up to max(1, key_pool.size) keys, then fallback model
        models_to_try = [route.primary, route.fallback]
        key_attempts = max(1, self._key_pool.size)

        last_status = 0
        last_body = ""
        for model_idx, model in enumerate(models_to_try):
            attempts_for_model = key_attempts if model_idx == 0 else 1
            for _ in range(attempts_for_model):
                api_key = self._key_pool.acquire(model, user_api_key=user_api_key)
                logger.info("Dispatching role=%s to model=%s", role.value, model)
                resp = await self._transport(api_key, model, messages, json_mode)
                last_status = resp.status_code
                last_body = shield(resp.content[:300])
                self._key_pool.record_response(
                    api_key,
                    model,
                    status_code=resp.status_code,
                    remaining_tokens=resp.remaining_tokens,
                    remaining_requests=resp.remaining_requests,
                )
                if resp.status_code == 200:
                    return resp.content

        raise GroqAdapterError(
            f"All Groq keys and fallback models failed for role '{role.value}' "
            f"(last_status={last_status}, body={last_body})"
        )

    async def complete_structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        role: AgentRole = AgentRole.LIGHTWEIGHT_PARSER,
        retries: int = 2,
    ) -> T:
        return await call_structured(self, prompt, schema, role=role, retries=retries)
