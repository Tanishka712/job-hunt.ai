"""FastAPI entrypoint for MINT Job Hunt AI."""

from fastapi import FastAPI

from app.adapters.llm.groq_adapter import GroqAdapter
from app.api.jobs import router as jobs_router
from app.api.resume import router as resume_router
from app.core.container import StorageContainer, build_in_memory_storage
from app.core.settings import get_settings
from app.ports.llm import LLMClient


def create_app(
    *,
    storage: StorageContainer | None = None,
    llm: LLMClient | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()
    application = FastAPI(title="MINT Job Hunt AI", version="0.1.0")
    application.state.storage = storage or build_in_memory_storage()
    application.state.llm = llm or GroqAdapter(default_api_key=settings.active_groq_api_key())

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Return service liveness status."""
        return {"status": "ok"}

    @application.get("/version")
    async def version() -> dict[str, str]:
        """Return deployed git SHA and environment name."""
        curr = get_settings()
        return {
            "git_sha": curr.git_sha,
            "environment": curr.environment,
        }

    application.include_router(jobs_router)
    application.include_router(resume_router)
    return application


app = create_app()
