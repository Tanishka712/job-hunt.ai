"""FastAPI entrypoint for MINT Job Hunt AI (S0 Skeleton)."""

from fastapi import FastAPI

from app.core.settings import get_settings

app = FastAPI(title="MINT Job Hunt AI", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    """Return service liveness status."""
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict[str, str]:
    """Return deployed git SHA and environment name."""
    settings = get_settings()
    return {
        "git_sha": settings.git_sha,
        "environment": settings.environment,
    }
