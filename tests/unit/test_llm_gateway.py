"""Unit tests for S2 Multi-Model LLM Gateway, Structured Validator, Key Pool, and Budget Guard."""

from typing import Any

import pytest
from pydantic import BaseModel

from app.adapters.fakes.llm import FakeLLM
from app.adapters.llm.groq_adapter import GroqAdapter, GroqTransportResponse
from app.adapters.llm.key_pool import GroqKeyPool, NoAvailableGroqKeyError
from app.guardrails.budget import BudgetExceededError, TokenBudgetGuard
from app.guardrails.validator import StructuredOutputError, call_structured
from app.ports.llm import ROLE_MODEL_ROUTES, AgentRole


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
    # Confirm error feedback was appended on retry 1 and retry 2
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
        max_tokens_per_model_day={"llama-3.1-8b-instant": 800},
    )

    await guard.consume(
        run_id="run-1",
        user_id="user-1",
        model="llama-3.1-8b-instant",
        tokens=400,
    )
    assert guard.remaining_model_tokens("llama-3.1-8b-instant") == 400

    # Exceeding run budget (400 + 200 > 500) trips BudgetExceededError
    with pytest.raises(BudgetExceededError, match="run budget"):
        await guard.consume(
            run_id="run-1",
            user_id="user-1",
            model="llama-3.1-8b-instant",
            tokens=200,
        )

    # New run, but exceeding model daily budget (400 + 450 > 800) trips BudgetExceededError
    with pytest.raises(BudgetExceededError, match="model daily budget"):
        await guard.consume(
            run_id="run-2",
            user_id="user-1",
            model="llama-3.1-8b-instant",
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
async def test_groq_adapter_key_rotation_and_fallback_model() -> None:
    """GroqAdapter rotates keys on 429 and falls back to secondary model if primary fails."""
    pool = GroqKeyPool(["gsk_key_one_111111111111", "gsk_key_two_222222222222"])
    recorded_calls: list[tuple[str, str]] = []

    async def fake_transport(
        api_key: str, model: str, messages: list[dict[str, Any]], json_mode: bool
    ) -> GroqTransportResponse:
        recorded_calls.append((api_key, model))
        # First call on key_one + primary model returns 429 rate limit
        if api_key == "gsk_key_one_111111111111" and model == "openai/gpt-oss-120b":
            return GroqTransportResponse(
                status_code=429,
                content="",
                remaining_tokens=0,
                remaining_requests=0,
            )
        # Second call rotates to key_two + primary model -> simulate 503 so fallback model is tested
        if api_key == "gsk_key_two_222222222222" and model == "openai/gpt-oss-120b":
            return GroqTransportResponse(
                status_code=503,
                content="",
                remaining_tokens=150_000,
                remaining_requests=900,
            )
        # Third call uses fallback model `qwen/qwen3.8-27b` and succeeds
        return GroqTransportResponse(
            status_code=200,
            content='{"title": "Staff AI Engineer", "company": "Acme", "skills": ["LangGraph"]}',
            remaining_tokens=180_000,
            remaining_requests=950,
            tokens_used=120,
        )

    adapter = GroqAdapter(key_pool=pool, transport=fake_transport)
    res = await adapter.complete_structured(
        "Parse resume requirements for contact@example.com",
        _SampleJobExtract,
        role=AgentRole.ANALYTICAL_REASONER,
    )
    assert res.title == "Staff AI Engineer"
    assert recorded_calls == [
        ("gsk_key_one_111111111111", "openai/gpt-oss-120b"),
        ("gsk_key_two_222222222222", "openai/gpt-oss-120b"),
        ("gsk_key_one_111111111111", "qwen/qwen3.8-27b"),
    ]


@pytest.mark.unit
def test_empty_key_pool_raises() -> None:
    """GroqKeyPool with no keys raises NoAvailableGroqKeyError."""
    pool = GroqKeyPool([])
    with pytest.raises(NoAvailableGroqKeyError):
        pool.acquire("llama-3.1-8b-instant")
