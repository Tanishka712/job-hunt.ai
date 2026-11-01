"""Live smoke tests for Groq multi-model gateway (excluded from offline CI)."""

import pytest
from pydantic import BaseModel

from app.adapters.llm.groq_adapter import GroqAdapter
from app.adapters.llm.key_pool import GroqKeyPool
from app.core.settings import get_settings
from app.ports.llm import AgentRole


class _PingSchema(BaseModel):
    status: str


@pytest.mark.live
async def test_live_groq_lightweight_parser() -> None:
    """Smoke-test live Groq API with LIGHTWEIGHT_PARSER (`llama-3.1-8b-instant`)."""
    settings = get_settings()
    keys = settings.parsed_groq_keys()
    if not keys:
        pytest.skip("No GROQ_API_KEYS configured in .env")

    adapter = GroqAdapter(key_pool=GroqKeyPool(keys))
    result = await adapter.complete_structured(
        'Return a JSON object with status set to "ok".',
        _PingSchema,
        role=AgentRole.LIGHTWEIGHT_PARSER,
    )
    assert result.status.lower() == "ok"
