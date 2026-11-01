"""Safety tests for S1 storage layer: multi-user isolation, credential ban, and port purity."""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.adapters.fakes.storage import (
    InMemoryApplicationRepo,
    InMemoryJobHashRepo,
    InMemoryOutreachLogRepo,
    InMemoryVectorStore,
)
from app.ports.storage import (
    ApplicationRecord,
    ApplicationStatus,
    CVChunk,
    UserProfile,
)


@pytest.mark.safety
def test_user_profile_forbids_passwords_and_secrets() -> None:
    """UserProfile must reject secret/credential fields (passwords live only in Key Vault)."""
    with pytest.raises(ValidationError):
        UserProfile.model_validate(
            {
                "user_id": "user-1",
                "full_name": "Ada Lovelace",
                "email": "ada@example.com",
                "password": "super-secret-password",
            }
        )

    with pytest.raises(ValidationError):
        UserProfile.model_validate(
            {
                "user_id": "user-1",
                "full_name": "Ada Lovelace",
                "email": "ada@example.com",
                "api_token": "secret-token",
            }
        )


@pytest.mark.safety
async def test_multi_user_isolation_across_repos() -> None:
    """User A's CV chunks, job hashes, applications, and outreach logs never leak to User B."""
    vector_store = InMemoryVectorStore()
    job_hash_repo = InMemoryJobHashRepo()
    app_repo = InMemoryApplicationRepo()
    outreach_repo = InMemoryOutreachLogRepo()

    await vector_store.upsert_chunks(
        [
            CVChunk(
                id="userA-chunk-1",
                user_id="user-A",
                content="User A proprietary quant trading strategy in Rust.",
                section="experience",
                source="cv-a.md",
                tags=["rust", "quant"],
            )
        ]
    )
    await job_hash_repo.put("user-A", "hash-123", {"title": "Quant Dev"})
    await app_repo.upsert(
        ApplicationRecord(
            user_id="user-A",
            job_id="job-1",
            company="Citadel",
            role_title="Quant Dev",
            status=ApplicationStatus.AWAITING_APPROVAL,
        )
    )
    await outreach_repo.record_contact("user-A", "recruiter-1", {"company": "Citadel"})

    # User B queries must see zero data from User A
    assert await vector_store.search("user-B", "quant trading Rust", top_k=5) == []
    assert await job_hash_repo.exists("user-B", "hash-123") is False
    assert await app_repo.get("user-B", "job-1") is None
    assert await app_repo.list_by_user("user-B") == []
    assert await outreach_repo.was_contacted("user-B", "recruiter-1") is False


@pytest.mark.safety
def test_ports_module_has_zero_external_sdk_imports() -> None:
    """src/app/ports/storage.py must only define protocols/models and never import azure/groq."""
    ports_file = Path("src/app/ports/storage.py")
    tree = ast.parse(ports_file.read_text(encoding="utf-8"))
    forbidden_prefixes = ("azure", "groq", "openai", "httpx")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(forbidden_prefixes), (
                    f"Forbidden SDK import '{alias.name}' in ports/storage.py"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(forbidden_prefixes), (
                f"Forbidden SDK import from '{node.module}' in ports/storage.py"
            )
