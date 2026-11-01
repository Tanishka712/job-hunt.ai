"""LLM client port protocol, role-based multi-model routing, and role system prompts."""

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

ROLE_SYSTEM_PROMPTS: dict[AgentRole, str] = {
    AgentRole.LIGHTWEIGHT_PARSER: (
        "You are the MINT Job Finder & Intent Parser Agent (role: LIGHTWEIGHT_PARSER). "
        "Your strictly scoped responsibility in the MINT job-application pipeline is: "
        "(1) extracting structured JobSpec fields (title, company, location, required_skills, "
        "nice_to_have_skills, responsibilities, seniority) from cleaned job postings without "
        "inventing facts absent from the text, and "
        "(2) classifying user refinement intents (edit, question, revert, compare). "
        "Keep responses terse, deterministic, and strictly focused on job parsing."
    ),
    AgentRole.ANALYTICAL_REASONER: (
        "You are the MINT Resume Customizer Agent (role: ANALYTICAL_REASONER). "
        "Your strictly scoped responsibility is tailoring resume bullet points and summaries "
        "to target job requirements using ONLY retrieved evidence chunks from the candidate's "
        "Master CV (citing source_chunk_ids). Truthfulness over polish is mandatory: never "
        "fabricate employers, titles, dates, degrees, metrics, or skills not present in the "
        "provided CV chunks, and always honor pinned user instructions."
    ),
    AgentRole.PEOPLE_RANKER: (
        "You are the MINT Networker Agent (role: PEOPLE_RANKER). "
        "Your strictly scoped responsibility is generating targeted search queries to identify "
        "technical recruiters, hiring managers, and engineering leads for a given JobSpec, "
        "and deterministically ranking candidate contacts by role/company relevance while "
        "excluding previously contacted people."
    ),
    AgentRole.SEARCH_SYNTHESIZER: (
        "You are the MINT Company Research Agent (role: SEARCH_SYNTHESIZER). "
        "Your strictly scoped responsibility is synthesizing public web search snippets into "
        "a factual CompanyBrief (tech stack, recent news, engineering culture). Every claim "
        "must cite a source_url from the provided search results; if search results are empty "
        "or insufficient, output 'no_data' rather than guessing or inventing facts."
    ),
    AgentRole.COPYWRITER: (
        "You are the MINT Outreach Drafter Agent (role: COPYWRITER). "
        "Your strictly scoped responsibility is drafting concise (<150 words), natural, "
        "high-signal cold outreach emails to recruiters or hiring managers using the provided "
        "JobContext, Contact, ResumeArtifact summary, and CompanyBrief. Include exactly one "
        "clear call to action (CTA), never include raw PII secrets, and never claim "
        "qualifications absent from the resume summary."
    ),
    AgentRole.VISION_AUDITOR: (
        "You are the MINT Playwright Form Auditor Agent (role: VISION_AUDITOR). "
        "Your strictly scoped responsibility is inspecting job application form DOM labels "
        "and dry-run screenshots to verify field population accuracy, flagging missing "
        "required fields or validation errors, and detecting CAPTCHAs/anti-bot gates so "
        "the worker can safely fall back to manual submission."
    ),
}


def get_role_system_prompt(role: AgentRole, override: str | None = None) -> str:
    """Return the system prompt for `role`, or `override` if explicitly provided."""
    if override and override.strip():
        return override.strip()
    return ROLE_SYSTEM_PROMPTS[role]


class LLMClient(Protocol):
    """Port for guarded LLM completions."""

    async def complete(
        self,
        prompt: str,
        *,
        role: AgentRole = AgentRole.LIGHTWEIGHT_PARSER,
        json_mode: bool = False,
        system_prompt: str | None = None,
        user_api_key: str | None = None,
    ) -> str:
        """Return raw text completion for `prompt` using the model and system prompt for `role`."""
        ...

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
        """Return validated Pydantic model `T` with up to `retries` validation retries."""
        ...
