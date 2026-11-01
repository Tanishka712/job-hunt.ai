"""Golden-set evaluation tests for S3 Job Finder Agent and CV Match Scorer."""

import pytest

from app.adapters.fakes.llm import FakeLLM
from app.agents.job_finder.graph import run_job_finder
from app.agents.job_finder.schemas import JobIngestRequest, JobIngestStatus, SeniorityLevel
from app.core.container import build_in_memory_storage
from app.core.seed import seed_user_data

GOLDEN_JOB_CASES = [
    {
        "name": "ai_agent_engineer_high_match",
        "url": "https://jobs.example.com/golden/1",
        "raw_html": (
            "<h1>AI Agent Engineer</h1><p>Company: LangSystems</p>"
            "<p>Skills: Python, FastAPI, LangGraph, Azure Cosmos DB, Docker</p>"
        ),
        "llm_json": """{
            "title": "AI Agent Engineer",
            "company": "LangSystems",
            "location": "Remote",
            "remote_policy": "remote",
            "seniority": "senior",
            "required_skills": ["Python", "FastAPI", "LangGraph", "Azure Cosmos DB", "Docker"],
            "nice_to_have_skills": ["Pydantic"],
            "responsibilities": ["Build multi-agent DAGs with LangGraph and FastAPI"],
            "salary_range": "$160k-$190k",
            "source_url": "https://jobs.example.com/golden/1",
            "is_job_posting": true
        }""",
        "expected_seniority": SeniorityLevel.SENIOR,
        "min_score": 70.0,
        "expect_qualified": True,
    },
    {
        "name": "backend_python_engineer_qualified",
        "url": "https://jobs.example.com/golden/2",
        "raw_html": (
            "<h1>Backend Software Engineer</h1><p>Company: CloudScale</p>"
            "<p>Skills: Python, FastAPI, Azure</p>"
        ),
        "llm_json": """{
            "title": "Backend Software Engineer",
            "company": "CloudScale",
            "location": "Bengaluru / Remote",
            "remote_policy": "hybrid",
            "seniority": "mid",
            "required_skills": ["Python", "FastAPI", "Azure"],
            "nice_to_have_skills": ["Docker"],
            "responsibilities": ["Develop REST APIs in FastAPI"],
            "salary_range": "",
            "source_url": "https://jobs.example.com/golden/2",
            "is_job_posting": true
        }""",
        "expected_seniority": SeniorityLevel.MID,
        "min_score": 65.0,
        "expect_qualified": True,
    },
    {
        "name": "ml_platform_engineer_qualified",
        "url": "https://jobs.example.com/golden/3",
        "raw_html": (
            "<h1>Machine Learning Engineer</h1><p>Company: VectorAI</p>"
            "<p>Skills: Python, Azure AI Search, Vector Databases</p>"
        ),
        "llm_json": """{
            "title": "Machine Learning Engineer",
            "company": "VectorAI",
            "location": "Remote",
            "remote_policy": "remote",
            "seniority": "senior",
            "required_skills": ["Python", "Azure AI Search", "FastAPI"],
            "nice_to_have_skills": [],
            "responsibilities": ["Scale semantic vector search indices"],
            "salary_range": "",
            "source_url": "https://jobs.example.com/golden/3",
            "is_job_posting": true
        }""",
        "expected_seniority": SeniorityLevel.SENIOR,
        "min_score": 65.0,
        "expect_qualified": True,
    },
    {
        "name": "ios_swift_developer_low_match",
        "url": "https://jobs.example.com/golden/4",
        "raw_html": (
            "<h1>iOS Swift UI Developer</h1><p>Company: MobileFirst</p>"
            "<p>Skills: Swift, SwiftUI, Objective-C, Xcode</p>"
        ),
        "llm_json": """{
            "title": "iOS Swift UI Developer",
            "company": "MobileFirst",
            "location": "Onsite NYC",
            "remote_policy": "onsite",
            "seniority": "mid",
            "required_skills": ["Swift", "SwiftUI", "Objective-C", "Xcode", "CoreData"],
            "nice_to_have_skills": ["Metal"],
            "responsibilities": ["Build native iPhone apps in SwiftUI"],
            "salary_range": "",
            "source_url": "https://jobs.example.com/golden/4",
            "is_job_posting": true
        }""",
        "expected_seniority": SeniorityLevel.MID,
        "min_score": 0.0,
        "expect_qualified": False,
    },
    {
        "name": "accounting_clerk_low_match",
        "url": "https://jobs.example.com/golden/5",
        "raw_html": (
            "<h1>Certified Public Accountant</h1><p>Company: Ledger Partners</p>"
            "<p>Skills: GAAP, QuickBooks, Tax Audits</p>"
        ),
        "llm_json": """{
            "title": "Certified Public Accountant",
            "company": "Ledger Partners",
            "location": "Chicago, IL",
            "remote_policy": "onsite",
            "seniority": "senior",
            "required_skills": ["GAAP", "QuickBooks", "Tax Audits", "CPA License"],
            "nice_to_have_skills": [],
            "responsibilities": ["Prepare corporate tax filings"],
            "salary_range": "",
            "source_url": "https://jobs.example.com/golden/5",
            "is_job_posting": true
        }""",
        "expected_seniority": SeniorityLevel.SENIOR,
        "min_score": 0.0,
        "expect_qualified": False,
    },
]


@pytest.mark.eval
@pytest.mark.parametrize("case", GOLDEN_JOB_CASES, ids=[str(c["name"]) for c in GOLDEN_JOB_CASES])
async def test_golden_job_finder_cases(case: dict[str, object]) -> None:
    """Golden-set evaluation for S3 Job Finder schema extraction and CV match scoring."""
    storage = build_in_memory_storage()
    await seed_user_data(
        user_id="eval-user",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )
    fake_llm = FakeLLM(scripted_responses=[str(case["llm_json"])])

    result = await run_job_finder(
        JobIngestRequest(
            url=str(case["url"]),
            user_id="eval-user",
            raw_html_override=str(case["raw_html"]),
            match_threshold=65.0,
        ),
        llm=fake_llm,
        storage=storage,
    )

    assert result.status == JobIngestStatus.PARSED
    assert result.job_spec is not None
    assert result.job_spec.seniority == case["expected_seniority"]
    assert 0.0 <= result.match_score <= 100.0
    assert result.match_score >= float(str(case["min_score"]))
    assert result.qualified_for_tailoring is bool(case["expect_qualified"])
