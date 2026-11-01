"""Pydantic schemas for S4 Resume Customizer drafts, verifier reports, artifacts, and API."""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.agents.job_finder.schemas import JobSpec


class ResumeBullet(BaseModel):
    """Single tailored resume bullet backed by one or more master CV chunk IDs."""

    text: str
    source_chunk_ids: list[str] = Field(min_length=1)


class ResumeDraftContent(BaseModel):
    """Structured LLM draft output for a tailored resume."""

    professional_summary: str
    bullets: list[ResumeBullet] = Field(min_length=1)
    highlighted_skills: list[str] = Field(default_factory=list)


class ResumeVerifierReport(BaseModel):
    """Deterministic truthfulness, citation, one-page, and pinned-constraint report."""

    passed: bool
    checked_bullets: int
    valid_chunk_citations: bool
    no_invented_claims: bool
    one_page_ok: bool
    pii_free: bool
    violations: list[str] = Field(default_factory=list)


class ResumeArtifact(BaseModel):
    """Typed handoff artifact produced by S4 Resume Customizer Agent."""

    version: int
    job_id: str
    user_id: str
    blob_url: str
    markdown_blob_url: str
    summary: str
    source_chunk_ids: list[str]
    draft: ResumeDraftContent
    verifier_report: ResumeVerifierReport


class RefinementIntent(StrEnum):
    """Supported conversational refinement intents."""

    EDIT = "edit"
    QUESTION = "question"
    REVERT = "revert"
    COMPARE = "compare"
    APPROVE = "approve"


class IntentClassification(BaseModel):
    """Structured output of the lightweight intent classifier node."""

    intent: RefinementIntent = RefinementIntent.EDIT
    pinned_instruction_to_add: str | None = None
    target_version: int | None = None
    compare_from_version: int | None = None


class ResumeRefineResult(BaseModel):
    """Response returned by a conversational turn on the S4 Resume Customizer."""

    session_id: str
    intent: RefinementIntent
    reply: str
    current_version: int
    artifact: ResumeArtifact | None = None
    verifier_report: ResumeVerifierReport | None = None
    diff_text: str | None = None


class CreateResumeRequest(BaseModel):
    """API request body for `POST /jobs/{job_id}/resume`."""

    user_id: str = "default-user"
    job_spec: JobSpec
    pinned_instructions: list[str] = Field(default_factory=list)
    user_api_key: str | None = None


class RefineResumeRequest(BaseModel):
    """API request body for `POST /jobs/{job_id}/resume/refine`."""

    user_id: str = "default-user"
    message: str
    user_api_key: str | None = None


class RevertResumeRequest(BaseModel):
    """API request body for `POST /jobs/{job_id}/resume/revert`."""

    user_id: str = "default-user"
    version: int
