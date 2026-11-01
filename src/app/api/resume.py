"""FastAPI endpoints for S4 Resume Customizer Agent (`/jobs/{job_id}/resume/*`)."""

from fastapi import APIRouter, HTTPException, Request

from app.adapters.llm.groq_adapter import MissingAPIKeyError, RateLimitExceededError
from app.agents.resume.graph import (
    create_initial_resume,
    list_resume_versions,
    refine_resume,
    revert_resume_version,
)
from app.agents.resume.schemas import (
    CreateResumeRequest,
    RefineResumeRequest,
    ResumeArtifact,
    ResumeRefineResult,
    RevertResumeRequest,
)
from app.core.container import StorageContainer
from app.ports.llm import LLMClient

router = APIRouter(prefix="/jobs/{job_id}/resume", tags=["resume"])


def _get_storage(request: Request) -> StorageContainer:
    storage: StorageContainer = request.app.state.storage
    return storage


def _get_llm(request: Request) -> LLMClient:
    llm: LLMClient = request.app.state.llm
    return llm


@router.post("", response_model=ResumeArtifact)
async def create_resume_endpoint(
    job_id: str,
    payload: CreateResumeRequest,
    request: Request,
) -> ResumeArtifact:
    """Create initial tailored resume (version 1) for `(user_id, job_id)`."""
    try:
        return await create_initial_resume(
            user_id=payload.user_id,
            job_id=job_id,
            job_spec=payload.job_spec,
            llm=_get_llm(request),
            storage=_get_storage(request),
            pinned_instructions=payload.pinned_instructions,
            user_api_key=payload.user_api_key,
        )
    except (RateLimitExceededError, MissingAPIKeyError) as exc:
        raise HTTPException(
            status_code=429 if isinstance(exc, RateLimitExceededError) else 401,
            detail={"message": str(exc), "ui_action": exc.ui_action},
        ) from exc


@router.post("/refine", response_model=ResumeRefineResult)
async def refine_resume_endpoint(
    job_id: str,
    payload: RefineResumeRequest,
    request: Request,
) -> ResumeRefineResult:
    """Run one conversational refinement turn (`edit`, `question`, `revert`, `compare`)."""
    try:
        return await refine_resume(
            user_id=payload.user_id,
            job_id=job_id,
            message=payload.message,
            llm=_get_llm(request),
            storage=_get_storage(request),
            user_api_key=payload.user_api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RateLimitExceededError, MissingAPIKeyError) as exc:
        raise HTTPException(
            status_code=429 if isinstance(exc, RateLimitExceededError) else 401,
            detail={"message": str(exc), "ui_action": exc.ui_action},
        ) from exc


@router.get("/versions", response_model=list[ResumeArtifact])
async def list_resume_versions_endpoint(
    job_id: str,
    request: Request,
    user_id: str = "default-user",
) -> list[ResumeArtifact]:
    """Return all saved `ResumeArtifact` versions for `(user_id, job_id)`."""
    return await list_resume_versions(
        user_id=user_id,
        job_id=job_id,
        storage=_get_storage(request),
    )


@router.post("/revert", response_model=ResumeRefineResult)
async def revert_resume_endpoint(
    job_id: str,
    payload: RevertResumeRequest,
    request: Request,
) -> ResumeRefineResult:
    """Revert the active resume for `(user_id, job_id)` to a previous version (0 LLM calls)."""
    try:
        return await revert_resume_version(
            user_id=payload.user_id,
            job_id=job_id,
            target_version=payload.version,
            storage=_get_storage(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
