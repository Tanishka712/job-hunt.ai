"""LLM client port protocol and role-based multi-model routing definitions."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AgentRole(StrEnum):
    """Cognitive role of an agent mapped to an independent Groq model bucket."""

    LIGHTWEIGHT_PARSER = "lightweight_parser"
    ANALYTICAL_REASONER = "analytical_reasoner"
    PEOPLE_RANKER = "people_ranker"
    SEARCH_SYNTHESIZER = "search_synthesizer"
    COPYWRITER = "copywriter"
    VISION_AUDITOR = "vision_auditor"


@dataclass(frozen=True)
class ModelRoute:
    """Primary and secondary overflow model IDs hosted on Groq."""

    primary: str
    fallback: str


ROLE_MODEL_ROUTES: dict[AgentRole, ModelRoute] = {
    AgentRole.LIGHTWEIGHT_PARSER: ModelRoute(
        primary="openai/gpt-oss-20b",
        fallback="allam-2-7b",
    ),
    AgentRole.ANALYTICAL_REASONER: ModelRoute(
        primary="openai/gpt-oss-120b",
        fallback="qwen/qwen3.8-27b",
    ),
    AgentRole.PEOPLE_RANKER: ModelRoute(
        primary="allam-2-7b",
        fallback="openai/gpt-oss-20b",
    ),
    AgentRole.SEARCH_SYNTHESIZER: ModelRoute(
        primary="qwen/qwen3.8-27b",
        fallback="openai/gpt-oss-20b",
    ),
    AgentRole.COPYWRITER: ModelRoute(
        primary="openai/gpt-oss-120b",
        fallback="qwen/qwen3.8-27b",
    ),
    AgentRole.VISION_AUDITOR: ModelRoute(
        primary="qwen/qwen3.8-27b",
        fallback="openai/gpt-oss-20b",
    ),
}


class LLMClient(Protocol):
    """Port for guarded LLM completions."""

    async def complete(
        self,
        prompt: str,
        *,
        role: AgentRole = AgentRole.LIGHTWEIGHT_PARSER,
        json_mode: bool = False,
    ) -> str:
        """Return raw text completion for `prompt` using the model routed for `role`."""
        ...

    async def complete_structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        role: AgentRole = AgentRole.LIGHTWEIGHT_PARSER,
        retries: int = 2,
    ) -> T:
        """Return validated Pydantic model `T` with up to `retries` validation retries."""
        ...
