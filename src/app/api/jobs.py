"""FastAPI endpoints for S3 Job Finder (`POST /jobs/ingest` and `POST /jobs/ingest-batch`)."""

from fastapi import APIRouter, HTTPException, Request

from app.adapters.llm.groq_adapter import MissingAPIKeyError, RateLimitExceededError
from app.agents.job_finder.graph import run_job_finder, run_job_finder_batch
from app.agents.job_finder.schemas import (
    BatchJobIngestRequest,
    JobIngestRequest,
    JobIngestResult,
)
from app.core.container import StorageContainer
from app.ports.llm import LLMClient

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _get_storage(request: Request) -> StorageContainer:
    storage: StorageContainer = request.app.state.storage
    return storage


def _get_llm(request: Request) -> LLMClient:
    llm: LLMClient = request.app.state.llm
    return llm


@router.post("/ingest", response_model=JobIngestResult)
async def ingest_job(payload: JobIngestRequest, request: Request) -> JobIngestResult:
    """Ingest a single job URL or raw HTML snippet through the S3 Job Finder agent."""
    try:
        return await run_job_finder(
            payload,
            llm=_get_llm(request),
            storage=_get_storage(request),
        )
    except (RateLimitExceededError, MissingAPIKeyError) as exc:
        raise HTTPException(
            status_code=429 if isinstance(exc, RateLimitExceededError) else 401,
            detail={
                "message": str(exc),
                "ui_action": exc.ui_action,
                "retry_after_seconds": getattr(exc, "retry_after_seconds", None),
            },
        ) from exc


@router.post("/ingest-batch", response_model=list[JobIngestResult])
async def ingest_job_batch(
    payload: BatchJobIngestRequest,
    request: Request,
) -> list[JobIngestResult]:
    """Ingest a batch of up to 50 job URLs through the S3 Job Finder agent."""
    try:
        return await run_job_finder_batch(
            payload.urls,
            user_id=payload.user_id,
            llm=_get_llm(request),
            storage=_get_storage(request),
            match_threshold=payload.match_threshold,
            user_api_key=payload.user_api_key,
        )
    except (RateLimitExceededError, MissingAPIKeyError) as exc:
        raise HTTPException(
            status_code=429 if isinstance(exc, RateLimitExceededError) else 401,
            detail={
                "message": str(exc),
                "ui_action": exc.ui_action,
                "retry_after_seconds": getattr(exc, "retry_after_seconds", None),
            },
        ) from exc
