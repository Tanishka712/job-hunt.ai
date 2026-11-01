"""Contract test suites for all S1 storage ports and idempotent seeding."""

import pytest

from app.adapters.fakes.storage import (
    FakeClock,
    InMemoryAgentSessionStore,
    InMemoryApplicationRepo,
    InMemoryBlobStore,
    InMemoryCompanyBriefCacheRepo,
    InMemoryGlobalJobCacheRepo,
    InMemoryJobHashRepo,
    InMemoryOutreachLogRepo,
    InMemoryProfileRepo,
    InMemoryThreadStore,
    InMemoryVectorStore,
)
from app.core.seed import MasterSeedInput, seed_master_data
from app.ports.storage import (
    ApplicationRecord,
    ApplicationStatus,
    ConcurrencyError,
    CVChunk,
    SASExpiredError,
    SessionTurnDoc,
    SessionVersionDoc,
    UserProfile,
)


@pytest.mark.contract
async def test_profile_repo_roundtrip() -> None:
    """ProfileRepo stores and retrieves UserProfile by user_id."""
    repo = InMemoryProfileRepo()
    assert await repo.get("user-1") is None

    profile = UserProfile(
        user_id="user-1",
        full_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1-555-0100",
        location="London, UK",
        links=["https://github.com/ada"],
        target_roles=["Staff ML Engineer", "AI Architect"],
    )
    await repo.upsert(profile)
    loaded = await repo.get("user-1")
    assert loaded == profile


@pytest.mark.contract
async def test_job_hash_repo_ttl_and_dedupe() -> None:
    """JobHashRepo configures 30-day default TTL and expires entries when clock advances."""
    clock = FakeClock(initial_epoch=1_000_000.0)
    repo = InMemoryJobHashRepo(clock=clock)
    assert repo.default_ttl_seconds == 2_592_000  # 30 days

    assert await repo.exists("user-1", "hash-abc") is False
    await repo.put("user-1", "hash-abc", {"title": "ML Engineer", "company": "Acme"})
    assert await repo.exists("user-1", "hash-abc") is True

    # Advance 29 days -> still exists
    clock.advance(29 * 86_400)
    assert await repo.exists("user-1", "hash-abc") is True

    # Advance 2 more days (31 days total) -> expired
    clock.advance(2 * 86_400)
    assert await repo.exists("user-1", "hash-abc") is False


@pytest.mark.contract
async def test_global_job_and_company_brief_caches_ttl() -> None:
    """GlobalJobCacheRepo (30d) and CompanyBriefCacheRepo (7d) cache across users and expire."""
    clock = FakeClock(initial_epoch=2_000_000.0)
    job_cache = InMemoryGlobalJobCacheRepo(clock=clock)
    company_cache = InMemoryCompanyBriefCacheRepo(clock=clock)

    assert job_cache.default_ttl_seconds == 2_592_000
    assert company_cache.default_ttl_seconds == 604_800

    await job_cache.put("https://jobs.example.com/123", {"title": "Backend Engineer"})
    await company_cache.put("acme-corp", {"summary": "Cloud infrastructure company"})

    assert await job_cache.get("https://jobs.example.com/123") == {"title": "Backend Engineer"}
    assert await company_cache.get("acme-corp") == {"summary": "Cloud infrastructure company"}

    # Advance 8 days -> company brief (7d TTL) expires, global job (30d TTL) remains valid
    clock.advance(8 * 86_400)
    assert await company_cache.get("acme-corp") is None
    assert await job_cache.get("https://jobs.example.com/123") == {"title": "Backend Engineer"}

    # Advance 23 more days -> global job also expires
    clock.advance(23 * 86_400)
    assert await job_cache.get("https://jobs.example.com/123") is None


@pytest.mark.contract
async def test_application_repo_and_thread_store() -> None:
    """ApplicationRepo tracks job status transitions; ThreadStore checkpoints DAG state."""
    app_repo = InMemoryApplicationRepo()
    thread_store = InMemoryThreadStore()

    record = ApplicationRecord(
        user_id="user-1",
        job_id="job-101",
        company="Acme",
        role_title="AI Engineer",
        status=ApplicationStatus.AWAITING_APPROVAL,
        match_score=88.5,
    )
    await app_repo.upsert(record)
    fetched = await app_repo.get("user-1", "job-101")
    assert fetched is not None
    assert fetched.status == ApplicationStatus.AWAITING_APPROVAL
    assert len(await app_repo.list_by_user("user-1")) == 1

    await thread_store.put_checkpoint("thread:user-1:job-101", {"step": "hitl_gate", "v": 1})
    cp = await thread_store.get_checkpoint("thread:user-1:job-101")
    assert cp == {"step": "hitl_gate", "v": 1}


@pytest.mark.contract
async def test_agent_session_store_etag_optimistic_concurrency() -> None:
    """AgentSessionStore enforces ETag checks on state updates and stores turns/versions."""
    store = InMemoryAgentSessionStore()
    session_id = "resume:user-1:job-101"

    assert await store.get_state(session_id) is None
    etag1 = await store.put_state(
        session_id,
        {"current_version": 1, "pinned_instructions": ["Keep to one page"]},
        expected_etag=None,
    )
    loaded, current_etag = await store.get_state_with_etag(session_id)
    assert loaded is not None
    assert loaded["current_version"] == 1
    assert current_etag == etag1

    # Stale ETag write must fail with ConcurrencyError
    with pytest.raises(ConcurrencyError):
        await store.put_state(
            session_id,
            {"current_version": 2, "pinned_instructions": ["Keep to one page"]},
            expected_etag="stale-etag-value",
        )

    # Matching ETag succeeds
    etag2 = await store.put_state(
        session_id,
        {"current_version": 2, "pinned_instructions": ["Keep to one page"]},
        expected_etag=etag1,
    )
    assert etag2 != etag1

    # Append turns and immutable versions
    await store.append_turn(
        SessionTurnDoc(
            session_id=session_id,
            turn_index=1,
            role="user",
            content="Make bullet 2 more quantitative",
            intent="edit",
            version_after=2,
        )
    )
    await store.save_version(
        SessionVersionDoc(
            session_id=session_id,
            version=2,
            content_ref="resumes-tailored/user-1/job-101/v2.pdf",
            created_by_turn=1,
            verifier_report={"passed": True},
            parent_version=1,
        )
    )
    turns = await store.list_turns(session_id)
    versions = await store.list_versions(session_id)
    assert len(turns) == 1
    assert turns[0].content == "Make bullet 2 more quantitative"
    assert len(versions) == 1
    assert versions[0].version == 2


@pytest.mark.contract
async def test_outreach_log_repo() -> None:
    """OutreachLogRepo prevents contacting the same person twice for the same user."""
    repo = InMemoryOutreachLogRepo()
    assert await repo.was_contacted("user-1", "linkedin.com/in/jane-recruiter") is False
    await repo.record_contact(
        "user-1",
        "linkedin.com/in/jane-recruiter",
        {"job_id": "job-101", "company": "Acme"},
    )
    assert await repo.was_contacted("user-1", "linkedin.com/in/jane-recruiter") is True


@pytest.mark.contract
async def test_blob_store_and_read_only_expiring_sas() -> None:
    """BlobStore uploads/downloads bytes and produces read-only SAS URLs that expire."""
    clock = FakeClock(initial_epoch=5_000_000.0)
    blob = InMemoryBlobStore(clock=clock)

    pdf_bytes = b"%PDF-1.4 sample resume content"
    uri = await blob.upload_bytes(
        "resumes-tailored",
        "user-1/job-101/v1.pdf",
        pdf_bytes,
        content_type="application/pdf",
    )
    assert "resumes-tailored/user-1/job-101/v1.pdf" in uri
    assert await blob.download_bytes("resumes-tailored", "user-1/job-101/v1.pdf") == pdf_bytes

    sas_url = await blob.generate_read_sas_url(
        "resumes-tailored",
        "user-1/job-101/v1.pdf",
        expires_in_seconds=600,
    )
    assert "sp=r" in sas_url
    assert "sp=w" not in sas_url
    assert await blob.download_via_sas(sas_url) == pdf_bytes

    # Advance clock past 600s expiry
    clock.advance(601)
    with pytest.raises(SASExpiredError):
        await blob.download_via_sas(sas_url)


@pytest.mark.contract
async def test_vector_store_returns_expected_chunk() -> None:
    """VectorStore retrieves the highest-matching CV chunk for a known query."""
    store = InMemoryVectorStore()
    chunks = [
        CVChunk(
            id="chunk-ml-1",
            user_id="user-1",
            content="Built distributed PyTorch training pipelines and RAG vector search on Azure.",
            section="experience",
            source="master-cv.md",
            tags=["pytorch", "rag", "azure"],
        ),
        CVChunk(
            id="chunk-fe-2",
            user_id="user-1",
            content="Designed responsive CSS layouts and Figma design tokens for marketing pages.",
            section="projects",
            source="master-cv.md",
            tags=["css", "figma", "frontend"],
        ),
    ]
    await store.upsert_chunks(chunks)

    results = await store.search("user-1", "PyTorch RAG vector search on Azure", top_k=1)
    assert len(results) == 1
    assert results[0].id == "chunk-ml-1"


@pytest.mark.contract
async def test_seed_master_data_is_idempotent() -> None:
    """Running seed_master_data twice produces identical state without duplicate chunks."""
    profile_repo = InMemoryProfileRepo()
    blob_store = InMemoryBlobStore()
    vector_store = InMemoryVectorStore()

    seed_input = MasterSeedInput(
        profile=UserProfile(
            user_id="user-1",
            full_name="Grace Hopper",
            email="grace@example.com",
            phone="+1-555-0199",
            location="New York, US",
            links=["https://github.com/grace"],
            target_roles=["Principal Compiler Engineer"],
        ),
        master_resume_bytes=b"# Grace Hopper\n- Built the first compiler (A-0) and COBOL.",
        chunks=[
            CVChunk(
                id="chunk-compiler-1",
                user_id="user-1",
                content="Invented the first linker/compiler (A-0) and led COBOL specification.",
                section="experience",
                source="master-cv.md",
                tags=["compilers", "cobol"],
            )
        ],
    )

    await seed_master_data(seed_input, profile_repo, blob_store, vector_store)
    await seed_master_data(seed_input, profile_repo, blob_store, vector_store)

    profile = await profile_repo.get("user-1")
    assert profile is not None
    assert profile.full_name == "Grace Hopper"

    results = await vector_store.search("user-1", "compiler COBOL", top_k=10)
    assert len(results) == 1
    assert results[0].id == "chunk-compiler-1"
