"""Unit tests for S0 health and version endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.main import app


@pytest.mark.unit
def test_health_returns_ok() -> None:
    """GET /health must return HTTP 200 and status ok."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.unit
def test_version_returns_git_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /version must return the configured GIT_SHA and environment."""
    monkeypatch.setenv("GIT_SHA", "abc1234deadbeef")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        response = client.get("/version")
        assert response.status_code == 200
        assert response.json() == {
            "git_sha": "abc1234deadbeef",
            "environment": "staging",
        }
    finally:
        get_settings.cache_clear()
