"""Golden-set evaluation tests for S4 Resume Customizer Agent."""

import json

import pytest

from app.adapters.fakes.llm import FakeLLM
from app.agents.job_finder.schemas import JobSpec, RemotePolicy, SeniorityLevel
from app.agents.resume.graph import create_initial_resume
from app.core.container import build_in_memory_storage
from app.core.seed import seed_user_data

GOLDEN_RESUME_CASES = [
    {
        "name": "ai_platform_engineer",
        "title": "Senior AI Platform Engineer",
        "skills": ["Python", "FastAPI", "LangGraph", "Docker"],
        "llm_json": json.dumps(
            {
                "professional_summary": (
                    "Senior AI Platform Engineer specializing in Python, FastAPI, "
                    "LangGraph, and Docker."
                ),
                "bullets": [
                    {
                        "text": (
                            "Architected multi-agent LLM workflows using Python, FastAPI, "
                            "LangGraph, and Pydantic on Azure Container Apps with Docker."
                        ),
                        "source_chunk_ids": ["eval-user-chunk-1"],
                    }
                ],
                "highlighted_skills": ["Python", "FastAPI", "LangGraph", "Docker"],
            }
        ),
    },
    {
        "name": "vector_search_engineer",
        "title": "Search & Retrieval Engineer",
        "skills": ["Azure AI Search", "Azure Cosmos DB", "Python"],
        "llm_json": json.dumps(
            {
                "professional_summary": (
                    "Search & Retrieval Engineer experienced with Azure AI Search "
                    "and Azure Cosmos DB."
                ),
                "bullets": [
                    {
                        "text": (
                            "Designed semantic vector search and cross-user caching pipelines "
                            "on Azure AI Search and Azure Cosmos DB."
                        ),
                        "source_chunk_ids": ["eval-user-chunk-2"],
                    }
                ],
                "highlighted_skills": ["Azure AI Search", "Azure Cosmos DB", "Python"],
            }
        ),
    },
    {
        "name": "backend_distributed_systems",
        "title": "Backend Distributed Systems Engineer",
        "skills": ["PostgreSQL", "Redis", "Python", "FastAPI"],
        "llm_json": json.dumps(
            {
                "professional_summary": (
                    "Backend Engineer building distributed systems with Python, "
                    "FastAPI, PostgreSQL, and Redis."
                ),
                "bullets": [
                    {
                        "text": ("Architected multi-agent LLM workflows using Python and FastAPI."),
                        "source_chunk_ids": ["eval-user-chunk-1"],
                    },
                    {
                        "text": (
                            "Designed semantic vector search and cross-user caching pipelines "
                            "on PostgreSQL and Redis."
                        ),
                        "source_chunk_ids": ["eval-user-chunk-2"],
                    },
                ],
                "highlighted_skills": ["Python", "FastAPI", "PostgreSQL", "Redis"],
            }
        ),
    },
    {
        "name": "ml_infra_pytorch",
        "title": "ML Infrastructure Engineer",
        "skills": ["PyTorch", "Kubernetes", "Docker"],
        "llm_json": json.dumps(
            {
                "professional_summary": (
                    "ML Infrastructure Engineer experienced in PyTorch, Kubernetes, and Docker."
                ),
                "bullets": [
                    {
                        "text": (
                            "Designed semantic vector search and cross-user caching pipelines "
                            "with PyTorch and Kubernetes."
                        ),
                        "source_chunk_ids": ["eval-user-chunk-2"],
                    }
                ],
                "highlighted_skills": ["PyTorch", "Kubernetes", "Docker"],
            }
        ),
    },
    {
        "name": "cloud_devops_azure",
        "title": "Azure Cloud Engineer",
        "skills": ["Azure", "Docker", "Azure Cosmos DB"],
        "llm_json": json.dumps(
            {
                "professional_summary": (
                    "Azure Cloud Engineer skilled in Azure Container Apps, Docker, "
                    "and Azure Cosmos DB."
                ),
                "bullets": [
                    {
                        "text": (
                            "Architected multi-agent LLM workflows on Azure Container Apps "
                            "with Docker."
                        ),
                        "source_chunk_ids": ["eval-user-chunk-1"],
                    }
                ],
                "highlighted_skills": ["Azure", "Docker", "Azure Cosmos DB"],
            }
        ),
    },
]


@pytest.mark.eval
@pytest.mark.parametrize(
    "case", GOLDEN_RESUME_CASES, ids=[str(c["name"]) for c in GOLDEN_RESUME_CASES]
)
async def test_golden_resume_cases(case: dict[str, object]) -> None:
    """Golden-set evaluation for S4 Resume Customizer truthfulness and citation validity."""
    storage = build_in_memory_storage()
    await seed_user_data(
        user_id="eval-user",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )
    fake_llm = FakeLLM(scripted_responses=[str(case["llm_json"])])
    skills = list(case["skills"]) if isinstance(case["skills"], list) else []
    spec = JobSpec(
        title=str(case["title"]),
        company="GoldenCorp",
        location="Remote",
        remote_policy=RemotePolicy.REMOTE,
        seniority=SeniorityLevel.SENIOR,
        required_skills=[str(s) for s in skills],
        responsibilities=["Deliver production AI systems"],
        source_url="https://jobs.example.com/golden",
        is_job_posting=True,
    )

    artifact = await create_initial_resume(
        user_id="eval-user",
        job_id=f"job-{case['name']}",
        job_spec=spec,
        llm=fake_llm,
        storage=storage,
        pinned_instructions=["Keep to one page"],
    )

    assert artifact.verifier_report.passed is True
    assert artifact.verifier_report.valid_chunk_citations is True
    assert artifact.verifier_report.no_invented_claims is True
    assert artifact.verifier_report.one_page_ok is True
    assert len(artifact.source_chunk_ids) >= 1
