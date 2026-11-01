"""Unit tests for S4 Resume Customizer Agent (state, verifier, memory, PDF, revert, isolation)."""

import json

import pytest
from fastapi.testclient import TestClient

from app.adapters.fakes.llm import FakeLLM
from app.agents.job_finder.schemas import JobSpec, RemotePolicy, SeniorityLevel
from app.agents.resume.graph import (
    compare_resume_versions,
    create_initial_resume,
    refine_resume,
    revert_resume_version,
)
from app.agents.resume.renderer import inspect_pdf_bytes
from app.agents.resume.schemas import RefinementIntent
from app.core.container import build_in_memory_storage
from app.core.seed import seed_user_data
from app.main import create_app


def _sample_job_spec(job_id_suffix: str = "acme") -> JobSpec:
    return JobSpec(
        title="Senior AI Platform Engineer",
        company=f"Acme Cloud ({job_id_suffix})",
        location="Remote",
        remote_policy=RemotePolicy.REMOTE,
        seniority=SeniorityLevel.SENIOR,
        required_skills=["Python", "FastAPI", "LangGraph", "Azure Cosmos DB", "Docker"],
        nice_to_have_skills=["Pydantic"],
        responsibilities=[
            "Architect multi-agent LLM workflows using Python, FastAPI, and LangGraph",
            "Scale semantic vector search on Azure AI Search and Azure Cosmos DB",
        ],
        source_url=f"https://jobs.example.com/{job_id_suffix}",
        is_job_posting=True,
    )


def _draft_json(summary: str, bullets: list[tuple[str, list[str]]], skills: list[str]) -> str:
    return json.dumps(
        {
            "professional_summary": summary,
            "bullets": [{"text": text, "source_chunk_ids": cids} for text, cids in bullets],
            "highlighted_skills": skills,
        }
    )


def _intent_json(
    intent: str = "edit",
    pinned: str | None = None,
    target_version: int | None = None,
    compare_from: int | None = None,
) -> str:
    return json.dumps(
        {
            "intent": intent,
            "pinned_instruction_to_add": pinned,
            "target_version": target_version,
            "compare_from_version": compare_from,
        }
    )


@pytest.mark.unit
async def test_initial_resume_draft_cites_chunks_and_renders_valid_one_page_pdf() -> None:
    """create_initial_resume retrieves CV chunks, verifies citations, and renders a 1-page PDF."""
    storage = build_in_memory_storage()
    await seed_user_data(
        user_id="user-1",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )
    fake_llm = FakeLLM(
        scripted_responses=[
            _draft_json(
                "AI Platform Engineer experienced in Python, FastAPI, LangGraph, and Cosmos DB.",
                [
                    (
                        "Architected multi-agent LLM workflows using Python, FastAPI, LangGraph, "
                        "and Pydantic on Azure Container Apps with Docker.",
                        ["user-1-chunk-1"],
                    ),
                    (
                        "Designed semantic vector search and cross-user caching pipelines on "
                        "Azure AI Search and Azure Cosmos DB.",
                        ["user-1-chunk-2"],
                    ),
                ],
                ["Python", "FastAPI", "LangGraph", "Azure Cosmos DB", "Docker"],
            )
        ]
    )

    artifact = await create_initial_resume(
        user_id="user-1",
        job_id="job-acme",
        job_spec=_sample_job_spec(),
        llm=fake_llm,
        storage=storage,
        pinned_instructions=["Keep to one page"],
    )

    assert artifact.version == 1
    assert artifact.verifier_report.passed is True
    assert artifact.verifier_report.valid_chunk_citations is True
    assert artifact.verifier_report.no_invented_claims is True
    assert artifact.verifier_report.one_page_ok is True
    assert set(artifact.source_chunk_ids) == {"user-1-chunk-1", "user-1-chunk-2"}

    pdf_bytes = await storage.blob_store.download_bytes(
        "resumes-tailored", "user-1/job-acme/v1.pdf"
    )
    is_valid_pdf, page_count = inspect_pdf_bytes(pdf_bytes)
    assert is_valid_pdf is True
    assert page_count == 1


@pytest.mark.unit
async def test_verifier_rejects_invented_claim_and_creates_no_version_on_exhaustion() -> None:
    """When FakeLLM invents a claim or fake chunk ID, verifier rejects and saves no version."""
    storage = build_in_memory_storage()
    await seed_user_data(
        user_id="user-1",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )

    valid_v1_json = _draft_json(
        "AI Engineer with Python and FastAPI experience.",
        [
            (
                "Architected multi-agent LLM workflows using Python, FastAPI, and LangGraph.",
                ["user-1-chunk-1"],
            )
        ],
        ["Python", "FastAPI", "LangGraph"],
    )
    invented_json = _draft_json(
        "Principal Quantum Researcher at Google DeepMind.",
        [
            (
                "Increased global ad revenue by 999% using quantum teleportation.",
                ["non-existent-chunk-999"],
            )
        ],
        ["Quantum"],
    )

    fake_llm = FakeLLM(
        scripted_responses=[
            valid_v1_json,
            _intent_json("edit"),
            invented_json,
            invented_json,
            invented_json,
        ]
    )

    await create_initial_resume(
        user_id="user-1",
        job_id="job-acme",
        job_spec=_sample_job_spec(),
        llm=fake_llm,
        storage=storage,
    )

    result = await refine_resume(
        user_id="user-1",
        job_id="job-acme",
        message="Add a bullet about my revenue impact",
        llm=fake_llm,
        storage=storage,
    )

    assert result.verifier_report is not None
    assert result.verifier_report.passed is False
    assert result.current_version == 1
    versions = await storage.agent_session_store.list_versions("resume:user-1:job-acme")
    assert len(versions) == 1


@pytest.mark.unit
async def test_pinned_preferences_persist_across_turns_and_trimming() -> None:
    """Pinned instruction from Turn 1 ('never mention Kubernetes') is enforced at Turn 3."""
    storage = build_in_memory_storage()
    await seed_user_data(
        user_id="user-1",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )

    v1_json = _draft_json(
        "AI Engineer skilled in Python, FastAPI, and LangGraph.",
        [
            (
                "Architected multi-agent LLM workflows using Python, FastAPI, and LangGraph.",
                ["user-1-chunk-1"],
            )
        ],
        ["Python", "FastAPI", "LangGraph"],
    )
    violating_k8s_json = _draft_json(
        "AI Engineer skilled in Python and Kubernetes.",
        [
            (
                "Designed semantic vector search pipelines on Azure AI Search and Kubernetes.",
                ["user-1-chunk-2"],
            )
        ],
        ["Python", "Kubernetes"],
    )
    compliant_v3_json = _draft_json(
        "AI Engineer skilled in Python, FastAPI, and Azure AI Search.",
        [
            (
                "Designed semantic vector search and cross-user caching pipelines on "
                "Azure AI Search and Azure Cosmos DB.",
                ["user-1-chunk-2"],
            )
        ],
        ["Python", "Azure AI Search", "Azure Cosmos DB"],
    )

    fake_llm = FakeLLM(
        scripted_responses=[
            v1_json,
            _intent_json("edit", pinned="Keep to one page and never mention Kubernetes"),
            v1_json,
            _intent_json("question"),
            "Your resume currently highlights Python, FastAPI, and LangGraph.",
            _intent_json("edit"),
            violating_k8s_json,
            compliant_v3_json,
        ]
    )

    await create_initial_resume(
        user_id="user-1",
        job_id="job-acme",
        job_spec=_sample_job_spec(),
        llm=fake_llm,
        storage=storage,
    )

    r1 = await refine_resume(
        user_id="user-1",
        job_id="job-acme",
        message="Always keep to one page and never mention Kubernetes.",
        llm=fake_llm,
        storage=storage,
    )
    assert r1.current_version == 2

    r2 = await refine_resume(
        user_id="user-1",
        job_id="job-acme",
        message="What skills are highlighted right now?",
        llm=fake_llm,
        storage=storage,
    )
    assert r2.intent == RefinementIntent.QUESTION
    assert r2.current_version == 2

    r3 = await refine_resume(
        user_id="user-1",
        job_id="job-acme",
        message="Emphasize my vector search experience from chunk 2.",
        llm=fake_llm,
        storage=storage,
    )
    assert r3.current_version == 3
    assert r3.artifact is not None
    assert "kubernetes" not in r3.artifact.summary.lower()
    assert all("kubernetes" not in b.text.lower() for b in r3.artifact.draft.bullets)


@pytest.mark.unit
async def test_revert_restores_previous_version_byte_for_byte_and_compare_diffs() -> None:
    """Reverting to v1 restores v1 PDF and Markdown byte-for-byte with 0 LLM calls."""
    storage = build_in_memory_storage()
    await seed_user_data(
        user_id="user-1",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )
    v1_json = _draft_json(
        "Summary Version One with Python and FastAPI.",
        [
            (
                "Architected multi-agent LLM workflows using Python and FastAPI.",
                ["user-1-chunk-1"],
            )
        ],
        ["Python", "FastAPI"],
    )
    v2_json = _draft_json(
        "Summary Version Two with Azure Cosmos DB and LangGraph.",
        [
            (
                "Designed semantic vector search pipelines on Azure AI Search and Azure Cosmos DB.",
                ["user-1-chunk-2"],
            )
        ],
        ["Azure Cosmos DB", "LangGraph"],
    )

    fake_llm = FakeLLM(scripted_responses=[v1_json, _intent_json("edit"), v2_json])

    await create_initial_resume(
        user_id="user-1",
        job_id="job-acme",
        job_spec=_sample_job_spec(),
        llm=fake_llm,
        storage=storage,
    )
    v1_pdf_original = await storage.blob_store.download_bytes(
        "resumes-tailored", "user-1/job-acme/v1.pdf"
    )
    v1_md_original = await storage.blob_store.download_bytes(
        "resumes-tailored", "user-1/job-acme/v1.md"
    )

    await refine_resume(
        user_id="user-1",
        job_id="job-acme",
        message="Focus on Azure Cosmos DB instead",
        llm=fake_llm,
        storage=storage,
    )
    calls_before_revert = len(fake_llm.calls)

    diff_res = await compare_resume_versions(
        user_id="user-1",
        job_id="job-acme",
        from_version=1,
        to_version=2,
        storage=storage,
    )
    assert "Summary Version One" in diff_res
    assert "Summary Version Two" in diff_res
    assert len(fake_llm.calls) == calls_before_revert

    revert_res = await revert_resume_version(
        user_id="user-1",
        job_id="job-acme",
        target_version=1,
        storage=storage,
    )
    assert len(fake_llm.calls) == calls_before_revert
    assert revert_res.current_version == 1
    assert revert_res.artifact is not None
    restored_pdf = await storage.blob_store.download_bytes(
        "resumes-tailored", "user-1/job-acme/v1.pdf"
    )
    restored_md = await storage.blob_store.download_bytes(
        "resumes-tailored", "user-1/job-acme/v1.md"
    )
    assert restored_pdf == v1_pdf_original
    assert restored_md == v1_md_original


@pytest.mark.unit
async def test_session_isolation_editing_job_a_never_changes_job_b() -> None:
    """Editing job-A never modifies job-B's state, versions, or blobs."""
    storage = build_in_memory_storage()
    await seed_user_data(
        user_id="user-1",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )
    draft_a = _draft_json(
        "Draft for Job A using Python and FastAPI.",
        [
            (
                "Architected multi-agent LLM workflows using Python and FastAPI.",
                ["user-1-chunk-1"],
            )
        ],
        ["Python"],
    )
    draft_b = _draft_json(
        "Draft for Job B using Azure AI Search.",
        [
            (
                "Designed semantic vector search pipelines on Azure AI Search.",
                ["user-1-chunk-2"],
            )
        ],
        ["Azure AI Search"],
    )
    draft_a_v2 = _draft_json(
        "Revised Draft for Job A with LangGraph.",
        [
            (
                "Architected multi-agent LLM workflows using Python, FastAPI, and LangGraph.",
                ["user-1-chunk-1"],
            )
        ],
        ["Python", "LangGraph"],
    )
    fake_llm = FakeLLM(
        scripted_responses=[
            draft_a,
            draft_b,
            _intent_json("edit", pinned="Never mention Docker"),
            draft_a_v2,
        ]
    )

    await create_initial_resume(
        user_id="user-1",
        job_id="job-A",
        job_spec=_sample_job_spec("A"),
        llm=fake_llm,
        storage=storage,
    )
    await create_initial_resume(
        user_id="user-1",
        job_id="job-B",
        job_spec=_sample_job_spec("B"),
        llm=fake_llm,
        storage=storage,
    )

    await refine_resume(
        user_id="user-1",
        job_id="job-A",
        message="Add LangGraph and never mention Docker",
        llm=fake_llm,
        storage=storage,
    )

    state_a = await storage.agent_session_store.get_state("resume:user-1:job-A")
    state_b = await storage.agent_session_store.get_state("resume:user-1:job-B")
    assert state_a is not None and state_b is not None
    assert state_a["current_version"] == 2
    assert state_b["current_version"] == 1
    assert state_b["pinned_instructions"] == []


@pytest.mark.unit
async def test_resume_fastapi_endpoints() -> None:
    """Test POST /jobs/{id}/resume, /refine, GET /versions, and POST /revert."""
    storage = build_in_memory_storage()
    await seed_user_data(
        user_id="user-1",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )
    v1_json = _draft_json(
        "Initial API Resume Summary with Python.",
        [
            (
                "Architected multi-agent LLM workflows using Python and FastAPI.",
                ["user-1-chunk-1"],
            )
        ],
        ["Python", "FastAPI"],
    )
    v2_json = _draft_json(
        "Second API Resume Summary with LangGraph.",
        [
            (
                "Architected multi-agent LLM workflows using Python, FastAPI, and LangGraph.",
                ["user-1-chunk-1"],
            )
        ],
        ["Python", "FastAPI", "LangGraph"],
    )
    fake_llm = FakeLLM(scripted_responses=[v1_json, _intent_json("edit"), v2_json])
    client = TestClient(create_app(storage=storage, llm=fake_llm))

    resp1 = client.post(
        "/jobs/job-101/resume",
        json={
            "user_id": "user-1",
            "job_spec": _sample_job_spec("101").model_dump(mode="json"),
            "pinned_instructions": ["Keep to one page"],
        },
    )
    assert resp1.status_code == 200
    assert resp1.json()["version"] == 1

    resp2 = client.post(
        "/jobs/job-101/resume/refine",
        json={"user_id": "user-1", "message": "Include LangGraph"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["current_version"] == 2

    resp3 = client.get("/jobs/job-101/resume/versions", params={"user_id": "user-1"})
    assert resp3.status_code == 200
    assert len(resp3.json()) == 2

    resp4 = client.post(
        "/jobs/job-101/resume/revert",
        json={"user_id": "user-1", "version": 1},
    )
    assert resp4.status_code == 200
    assert resp4.json()["current_version"] == 1
