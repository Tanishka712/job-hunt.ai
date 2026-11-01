"""Live tests for Groq multi-model gateway across all 4 active Groq models."""

import pytest
from pydantic import BaseModel

from app.adapters.llm.groq_adapter import GroqAdapter
from app.core.settings import get_settings
from app.ports.llm import AgentRole


class _LiveJobExtract(BaseModel):
    title: str
    company: str
    required_skills: list[str]


@pytest.mark.live
@pytest.mark.parametrize(
    "role",
    [
        AgentRole.LIGHTWEIGHT_PARSER,  # openai/gpt-oss-20b
        AgentRole.ANALYTICAL_REASONER,  # openai/gpt-oss-120b
        AgentRole.SEARCH_SYNTHESIZER,  # qwen/qwen3.8-27b
        AgentRole.PEOPLE_RANKER,  # allam-2-7b
    ],
)
async def test_live_groq_all_agent_roles_structured(role: AgentRole) -> None:
    """Verify real LLM calls across all 4 Groq models with PII shielding and Pydantic validation."""
    settings = get_settings()
    api_key = settings.active_groq_api_key()
    if not api_key:
        pytest.skip("No GROQ_API_KEY configured in .env")

    adapter = GroqAdapter(default_api_key=api_key)
    prompt = (
        "Job Posting: Acme AI is hiring a Senior Machine Learning Engineer. "
        "Required skills: Python, PyTorch, LangGraph. "
        "Send questions to recruiter.private@acme.io or +1-415-555-0199."
    )
    result = await adapter.complete_structured(
        prompt,
        _LiveJobExtract,
        role=role,
        retries=2,
    )
    assert "acme" in result.company.lower()
    assert len(result.required_skills) >= 1
