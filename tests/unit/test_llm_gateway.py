"""Unit tests for S2 Multi-Model LLM Gateway, BYOK, Rate-Limit UI Error, and Budget Guard."""

from typing import Any

import pytest
from pydantic import BaseModel

from app.adapters.fakes.llm import FakeLLM
from app.adapters.llm.groq_adapter import (
    GroqAdapter,
    GroqTransportResponse,
    MissingAPIKeyError,
    RateLimitExceededError,
)
from app.guardrails.budget import BudgetExceededError, TokenBudgetGuard
from app.guardrails.validator import StructuredOutputError, call_structured
from app.ports.llm import ROLE_MODEL_ROUTES, ROLE_SYSTEM_PROMPTS, AgentRole


class _SampleJobExtract(BaseModel):
    title: str
    company: str
    skills: list[str]


@pytest.mark.unit
async def test_validator_retries_exactly_twice_then_raises() -> None:
    """call_structured attempts 1 initial + 2 retries (3 total) and raises StructuredOutputError."""
    fake_llm = FakeLLM(
        scripted_responses=[
            "not json at all",
            '{"title": "Engineer"}',  # missing company and skills
            '{"title": "Engineer", "company": 123}',  # still invalid
            '{"title": "Engineer", "company": "Acme", "skills": ["Python"]}',  # 4th never reached
        ]
    )

    with pytest.raises(StructuredOutputError) as exc_info:
        await call_structured(
            fake_llm,
            "Extract job from HTML",
            _SampleJobExtract,
            role=AgentRole.LIGHTWEIGHT_PARSER,
            retries=2,
        )

    assert exc_info.value.attempts == 3
    assert len(fake_llm.calls) == 3
    assert "Validation error" in fake_llm.calls[1].prompt
    assert "Validation error" in fake_llm.calls[2].prompt


@pytest.mark.unit
async def test_validator_succeeds_on_second_attempt_and_shields_pii() -> None:
    """call_structured succeeds when retry returns valid JSON and redacts PII before calling LLM."""
    fake_llm = FakeLLM(
        scripted_responses=[
            "invalid json",
            '{"title": "ML Engineer", "company": "DeepTech", "skills": ["PyTorch", "Rust"]}',
        ]
    )

    parsed = await call_structured(
        fake_llm,
        "Candidate email secret@example.com applying to DeepTech",
        _SampleJobExtract,
        role=AgentRole.LIGHTWEIGHT_PARSER,
        retries=2,
    )
    assert parsed.company == "DeepTech"
    assert parsed.skills == ["PyTorch", "Rust"]
    assert len(fake_llm.calls) == 2
    assert "secret@example.com" not in fake_llm.calls[0].prompt


@pytest.mark.unit
async def test_token_budget_guard_trips_at_limit() -> None:
    """TokenBudgetGuard enforces per-run, per-user, and per-model daily token ceilings."""
    guard = TokenBudgetGuard(
        max_tokens_per_run=500,
        max_tokens_per_user_day=1_000,
        max_tokens_per_model_day={"openai/gpt-oss-20b": 800},
    )

    await guard.consume(
        run_id="run-1",
        user_id="user-1",
        model="openai/gpt-oss-20b",
        tokens=400,
    )
    assert guard.remaining_model_tokens("openai/gpt-oss-20b") == 400

    with pytest.raises(BudgetExceededError, match="run budget"):
        await guard.consume(
            run_id="run-1",
            user_id="user-1",
            model="openai/gpt-oss-20b",
            tokens=200,
        )

    with pytest.raises(BudgetExceededError, match="model daily budget"):
        await guard.consume(
            run_id="run-2",
            user_id="user-1",
            model="openai/gpt-oss-20b",
            tokens=450,
        )


@pytest.mark.unit
def test_role_model_routes_assign_distinct_groq_models() -> None:
    """Each AgentRole maps to the expected primary and fallback model on Groq."""
    assert ROLE_MODEL_ROUTES[AgentRole.LIGHTWEIGHT_PARSER].primary == "openai/gpt-oss-20b"
    assert ROLE_MODEL_ROUTES[AgentRole.ANALYTICAL_REASONER].primary == "openai/gpt-oss-120b"
    assert ROLE_MODEL_ROUTES[AgentRole.PEOPLE_RANKER].primary == "allam-2-7b"
    assert ROLE_MODEL_ROUTES[AgentRole.SEARCH_SYNTHESIZER].primary == "qwen/qwen3.8-27b"
    assert ROLE_MODEL_ROUTES[AgentRole.COPYWRITER].primary == "openai/gpt-oss-120b"
    assert ROLE_MODEL_ROUTES[AgentRole.VISION_AUDITOR].primary == "qwen/qwen3.8-27b"


@pytest.mark.unit
async def test_groq_adapter_byok_and_fallback_model() -> None:
    """GroqAdapter uses per-user BYOK key when provided and falls back to secondary model."""
    recorded_calls: list[tuple[str, str]] = []

    async def fake_transport(
        api_key: str, model: str, messages: list[dict[str, Any]], json_mode: bool
    ) -> GroqTransportResponse:
        recorded_calls.append((api_key, model))
        if model == "openai/gpt-oss-120b":
            return GroqTransportResponse(status_code=503, content="overloaded")
        return GroqTransportResponse(
            status_code=200,
            content='{"title": "Staff AI Engineer", "company": "Acme", "skills": ["LangGraph"]}',
            tokens_used=120,
        )

    adapter = GroqAdapter(default_api_key="default-system-key", transport=fake_transport)
    res = await adapter.complete_structured(
        "Parse resume requirements for contact@example.com",
        _SampleJobExtract,
        role=AgentRole.ANALYTICAL_REASONER,
        user_api_key="byok-user-custom-key",
    )
    assert res.title == "Staff AI Engineer"
    assert recorded_calls == [
        ("byok-user-custom-key", "openai/gpt-oss-120b"),
        ("byok-user-custom-key", "qwen/qwen3.8-27b"),
    ]


@pytest.mark.unit
async def test_groq_adapter_rate_limit_raises_clear_ui_error() -> None:
    """When rate limits are hit, raises RateLimitExceededError with ui_action=CHANGE_API_KEY."""

    async def rate_limited_transport(
        api_key: str, model: str, messages: list[dict[str, Any]], json_mode: bool
    ) -> GroqTransportResponse:
        return GroqTransportResponse(
            status_code=429,
            content="Rate limit reached",
            retry_after_seconds=45,
        )

    adapter = GroqAdapter(default_api_key="system-key", transport=rate_limited_transport)
    with pytest.raises(RateLimitExceededError) as exc_info:
        await adapter.complete("Hello", role=AgentRole.ANALYTICAL_REASONER)

    err = exc_info.value
    assert err.ui_action == "CHANGE_API_KEY"
    assert err.retry_after_seconds == 45
    assert "BYOK" in str(err)


@pytest.mark.unit
async def test_missing_api_key_raises_clear_ui_error() -> None:
    """GroqAdapter with no default key and no BYOK key raises MissingAPIKeyError for UI."""
    adapter = GroqAdapter(default_api_key="")
    with pytest.raises(MissingAPIKeyError) as exc_info:
        await adapter.complete("Hello")
    assert exc_info.value.ui_action == "CHANGE_API_KEY"


@pytest.mark.unit
async def test_role_system_prompts_injected_into_groq_messages() -> None:
    """Every AgentRole has a dedicated system prompt that GroqAdapter prepends as messages[0]."""
    for role in AgentRole:
        assert role in ROLE_SYSTEM_PROMPTS
        assert len(ROLE_SYSTEM_PROMPTS[role]) > 40

    captured_messages: list[dict[str, Any]] = []

    async def capture_transport(
        api_key: str, model: str, messages: list[dict[str, Any]], json_mode: bool
    ) -> GroqTransportResponse:
        captured_messages.extend(messages)
        return GroqTransportResponse(status_code=200, content="In-role response")

    adapter = GroqAdapter(default_api_key="sys-key", transport=capture_transport)
    await adapter.complete("how can you help", role=AgentRole.LIGHTWEIGHT_PARSER)

    assert len(captured_messages) == 2
    assert captured_messages[0]["role"] == "system"
    assert "MINT Job Finder & Intent Parser Agent" in captured_messages[0]["content"]
    assert captured_messages[1] == {"role": "user", "content": "how can you help"}
