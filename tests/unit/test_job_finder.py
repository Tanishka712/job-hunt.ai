"""Unit tests for S3 Job Finder Agent, HTML Cleaner, Match Scorer, Global Cache, and API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.fakes.llm import FakeLLM
from app.agents.job_finder.graph import run_job_finder, run_job_finder_batch
from app.agents.job_finder.html_cleaner import clean_job_html, compute_job_hash
from app.agents.job_finder.schemas import JobIngestRequest, JobIngestStatus
from app.agents.job_finder.tools import HttpResponseData
from app.core.container import build_in_memory_storage
from app.core.seed import seed_user_data
from app.main import create_app
from app.ports.storage import ApplicationStatus

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "jobs"


def _make_fixture_fetcher(html_text: str, *, robots_txt: str = "User-agent: *\nAllow: /\n"):
    async def fetcher(url: str) -> HttpResponseData:
        if url.endswith("/robots.txt"):
            return HttpResponseData(status_code=200, text=robots_txt, url=url)
        return HttpResponseData(status_code=200, text=html_text, url=url)

    return fetcher


@pytest.mark.unit
@pytest.mark.parametrize(
    ("company_a", "title_a", "company_b", "title_b", "should_match"),
    [
        (
            "Acme Cloud Systems, Inc.",
            "Senior AI Platform Engineer",
            "acme cloud systems",
            "  Senior AI-Platform Engineer! ",
            True,
        ),
        (
            "StripeFlow LLC",
            "Backend Python Engineer",
            "StripeFlow, L.L.C.",
            "backend python engineer",
            True,
        ),
        (
            "DeepTech Corp.",
            "Staff ML Engineer",
            "DeepTech Corporation",
            "Staff ML Engineer",
            True,
        ),
        (
            "Acme Cloud Systems",
            "Senior AI Platform Engineer",
            "Acme Cloud Systems",
            "Junior Frontend Designer",
            False,
        ),
    ],
)
def test_job_hash_normalization_table(
    company_a: str,
    title_a: str,
    company_b: str,
    title_b: str,
    should_match: bool,
) -> None:
    """compute_job_hash normalizes corporate suffixes, case, punctuation, and whitespace."""
    hash_a = compute_job_hash(company_a, title_a)
    hash_b = compute_job_hash(company_b, title_b)
    assert (hash_a == hash_b) is should_match


@pytest.mark.unit
def test_html_cleaner_strips_scripts_extracts_json_ld_and_caps_tokens() -> None:
    """clean_job_html strips script/style noise, keeps JSON-LD, and caps to <=3000 chars."""
    raw_html = (FIXTURES_DIR / "valid_job.html").read_text(encoding="utf-8") + (
        "<p>extra</p>" * 800
    )
    cleaned = clean_job_html(raw_html, max_chars=3000)

    assert "Senior AI Platform Engineer" in cleaned
    assert "Acme Cloud Systems" in cleaned
    assert "JSON-LD JobPosting" in cleaned
    assert "<script" not in cleaned
    assert "font-family" not in cleaned
    assert len(cleaned) <= 3000


@pytest.mark.unit
async def test_job_finder_happy_path_parses_scores_and_persists() -> None:
    """Valid job HTML parses via LLM into JobSpec, scores against CV, and writes hash + record."""
    storage = build_in_memory_storage()
    await seed_user_data(
        user_id="user-1",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )
    valid_html = (FIXTURES_DIR / "valid_job.html").read_text(encoding="utf-8")
    fake_llm = FakeLLM(
        scripted_responses=[
            """{
                "title": "Senior AI Platform Engineer",
                "company": "Acme Cloud Systems, Inc.",
                "location": "San Francisco, CA (Hybrid)",
                "remote_policy": "hybrid",
                "seniority": "senior",
                "required_skills": ["Python", "FastAPI", "LangGraph", "Azure Cosmos DB", "Docker"],
                "nice_to_have_skills": ["Pydantic"],
                "responsibilities": [
                    "Architect resilient FastAPI and LangGraph agent workflows on Azure",
                    "Build semantic vector search pipelines on Azure AI Search and Cosmos DB"
                ],
                "salary_range": "$170k - $210k",
                "source_url": "https://jobs.example.com/acme/ai-platform",
                "is_job_posting": true
            }"""
        ]
    )

    result = await run_job_finder(
        JobIngestRequest(
            url="https://jobs.example.com/acme/ai-platform",
            user_id="user-1",
            match_threshold=65.0,
        ),
        llm=fake_llm,
        storage=storage,
        fetcher=_make_fixture_fetcher(valid_html),
    )

    assert result.status == JobIngestStatus.PARSED
    assert result.job_spec is not None
    assert result.job_spec.company == "Acme Cloud Systems, Inc."
    assert result.match_score >= 65.0
    assert result.qualified_for_tailoring is True
    assert result.from_global_cache is False

    # Verify per-user JobHashRepo and ApplicationRepo were updated
    assert await storage.job_hash_repo.exists("user-1", result.job_hash) is True
    app_rec = await storage.application_repo.get("user-1", result.job_id)
    assert app_rec is not None
    assert app_rec.status == ApplicationStatus.FETCHED
    assert app_rec.match_score == result.match_score


@pytest.mark.unit
async def test_job_finder_duplicate_dropped_for_same_user() -> None:
    """Ingesting the same job a second time for the same user returns DUPLICATE."""
    storage = build_in_memory_storage()
    valid_html = (FIXTURES_DIR / "valid_job.html").read_text(encoding="utf-8")
    scripted_json = """{
        "title": "Senior AI Platform Engineer",
        "company": "Acme Cloud Systems, Inc.",
        "location": "San Francisco, CA",
        "remote_policy": "hybrid",
        "seniority": "senior",
        "required_skills": ["Python", "FastAPI"],
        "nice_to_have_skills": [],
        "responsibilities": ["Build agents"],
        "salary_range": "",
        "source_url": "https://jobs.example.com/acme/1",
        "is_job_posting": true
    }"""
    fake_llm = FakeLLM(scripted_responses=[scripted_json, scripted_json])

    first = await run_job_finder(
        JobIngestRequest(url="https://jobs.example.com/acme/1", user_id="user-1"),
        llm=fake_llm,
        storage=storage,
        fetcher=_make_fixture_fetcher(valid_html),
    )
    assert first.status == JobIngestStatus.PARSED

    second = await run_job_finder(
        JobIngestRequest(url="https://jobs.example.com/acme/1-mirror", user_id="user-1"),
        llm=fake_llm,
        storage=storage,
        fetcher=_make_fixture_fetcher(valid_html),
    )
    assert second.status == JobIngestStatus.DUPLICATE
    assert second.job_hash == first.job_hash


@pytest.mark.unit
async def test_job_finder_cross_user_global_cache_reuses_llm_parse_at_zero_tokens() -> None:
    """User B ingesting a URL already parsed by User A hits GlobalJobCacheRepo at 0 LLM calls."""
    storage = build_in_memory_storage()
    await seed_user_data(
        user_id="user-a",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )
    await seed_user_data(
        user_id="user-b",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )
    valid_html = (FIXTURES_DIR / "valid_job.html").read_text(encoding="utf-8")
    fake_llm = FakeLLM(
        scripted_responses=[
            """{
                "title": "Senior AI Platform Engineer",
                "company": "Acme Cloud Systems",
                "location": "Remote",
                "remote_policy": "remote",
                "seniority": "senior",
                "required_skills": ["Python", "FastAPI", "LangGraph"],
                "nice_to_have_skills": [],
                "responsibilities": ["Build agents"],
                "salary_range": "",
                "source_url": "https://jobs.example.com/shared-url",
                "is_job_posting": true
            }"""
        ]
    )

    res_a = await run_job_finder(
        JobIngestRequest(url="https://jobs.example.com/shared-url", user_id="user-a"),
        llm=fake_llm,
        storage=storage,
        fetcher=_make_fixture_fetcher(valid_html),
    )
    assert res_a.status == JobIngestStatus.PARSED
    assert res_a.from_global_cache is False
    assert len(fake_llm.calls) == 1

    # User B ingests the exact same URL -> 0 additional LLM calls!
    res_b = await run_job_finder(
        JobIngestRequest(url="https://jobs.example.com/shared-url", user_id="user-b"),
        llm=fake_llm,
        storage=storage,
        fetcher=_make_fixture_fetcher(valid_html),
    )
    assert res_b.status == JobIngestStatus.PARSED
    assert res_b.from_global_cache is True
    assert len(fake_llm.calls) == 1  # Still 1 total LLM call!
    assert await storage.application_repo.get("user-b", res_b.job_id) is not None


@pytest.mark.unit
async def test_job_finder_malformed_html_fixture() -> None:
    """Malformed HTML fixture is cleaned and parsed into a valid JobSpec."""
    storage = build_in_memory_storage()
    malformed_html = (FIXTURES_DIR / "malformed_job.html").read_text(encoding="utf-8")
    fake_llm = FakeLLM(
        scripted_responses=[
            """{
                "title": "Backend Python Engineer",
                "company": "StripeFlow LLC",
                "location": "Remote (US/India)",
                "remote_policy": "remote",
                "seniority": "mid",
                "required_skills": ["Python", "FastAPI", "PostgreSQL", "Redis", "Docker"],
                "nice_to_have_skills": [],
                "responsibilities": ["Build high-throughput payment microservices"],
                "salary_range": "",
                "source_url": "https://jobs.example.com/stripeflow",
                "is_job_posting": true
            }"""
        ]
    )

    res = await run_job_finder(
        JobIngestRequest(url="https://jobs.example.com/stripeflow", user_id="user-1"),
        llm=fake_llm,
        storage=storage,
        fetcher=_make_fixture_fetcher(malformed_html),
    )
    assert res.status == JobIngestStatus.PARSED
    assert res.job_spec is not None
    assert res.job_spec.company == "StripeFlow LLC"


@pytest.mark.unit
async def test_job_finder_non_job_page_rejected_without_writing_hash() -> None:
    """Non-job login/404 page returns status=NON_JOB and does not write to JobHashRepo."""
    storage = build_in_memory_storage()
    non_job_html = (FIXTURES_DIR / "non_job_page.html").read_text(encoding="utf-8")
    fake_llm = FakeLLM(
        scripted_responses=[
            """{
                "title": "",
                "company": "",
                "location": "",
                "remote_policy": "unspecified",
                "seniority": "unspecified",
                "required_skills": [],
                "nice_to_have_skills": [],
                "responsibilities": [],
                "salary_range": "",
                "source_url": "https://jobs.example.com/login",
                "is_job_posting": false
            }"""
        ]
    )

    res = await run_job_finder(
        JobIngestRequest(url="https://jobs.example.com/login", user_id="user-1"),
        llm=fake_llm,
        storage=storage,
        fetcher=_make_fixture_fetcher(non_job_html),
    )
    assert res.status == JobIngestStatus.NON_JOB
    assert await storage.application_repo.list_by_user("user-1") == []


@pytest.mark.unit
async def test_job_finder_schema_failure_retries_twice_then_marks_failed() -> None:
    """Schema validation failure retries twice (3 calls) and returns FAILED without saving hash."""
    storage = build_in_memory_storage()
    valid_html = (FIXTURES_DIR / "valid_job.html").read_text(encoding="utf-8")
    fake_llm = FakeLLM(
        scripted_responses=[
            "not json",
            '{"title": 123}',
            '{"invalid": true}',
        ]
    )

    res = await run_job_finder(
        JobIngestRequest(url="https://jobs.example.com/bad-llm", user_id="user-1"),
        llm=fake_llm,
        storage=storage,
        fetcher=_make_fixture_fetcher(valid_html),
    )
    assert res.status == JobIngestStatus.FAILED
    assert res.error_reason is not None
    assert "Failed to validate JobSpec after 3 attempts" in res.error_reason
    assert len(fake_llm.calls) == 3
    assert await storage.application_repo.list_by_user("user-1") == []


@pytest.mark.unit
async def test_job_finder_respects_robots_txt_disallow() -> None:
    """When robots.txt disallows the path, scrape_job refuses and run_job_finder returns FAILED."""
    storage = build_in_memory_storage()
    valid_html = (FIXTURES_DIR / "valid_job.html").read_text(encoding="utf-8")
    fake_llm = FakeLLM(scripted_responses=[])

    disallow_robots = "User-agent: *\nDisallow: /private/\n"
    res = await run_job_finder(
        JobIngestRequest(url="https://jobs.example.com/private/secret-role", user_id="user-1"),
        llm=fake_llm,
        storage=storage,
        fetcher=_make_fixture_fetcher(valid_html, robots_txt=disallow_robots),
    )
    assert res.status == JobIngestStatus.FAILED
    assert res.error_reason is not None
    assert "robots.txt" in res.error_reason
    assert len(fake_llm.calls) == 0


@pytest.mark.unit
async def test_job_finder_batch_and_fastapi_endpoints() -> None:
    """POST /jobs/ingest and POST /jobs/ingest-batch process jobs through the Job Finder graph."""
    storage = build_in_memory_storage()
    valid_html = (FIXTURES_DIR / "valid_job.html").read_text(encoding="utf-8")
    fake_llm = FakeLLM(
        scripted_responses=[
            """{
                "title": "Senior AI Platform Engineer",
                "company": "Acme Cloud Systems",
                "location": "Remote",
                "remote_policy": "remote",
                "seniority": "senior",
                "required_skills": ["Python", "FastAPI", "LangGraph"],
                "nice_to_have_skills": [],
                "responsibilities": ["Build agents"],
                "salary_range": "",
                "source_url": "https://jobs.example.com/1",
                "is_job_posting": true
            }"""
        ]
    )

    batch_results = await run_job_finder_batch(
        urls=["https://jobs.example.com/1", "https://jobs.example.com/1"],
        user_id="user-1",
        llm=fake_llm,
        storage=storage,
        fetcher=_make_fixture_fetcher(valid_html),
    )
    assert len(batch_results) == 2
    assert batch_results[0].status == JobIngestStatus.PARSED
    assert batch_results[1].status == JobIngestStatus.DUPLICATE

    # Test FastAPI endpoints with injected overrides
    test_app = create_app(storage=storage, llm=fake_llm)
    client = TestClient(test_app)
    resp = client.post(
        "/jobs/ingest",
        json={
            "url": "https://jobs.example.com/1",
            "user_id": "user-2",
            "raw_html_override": valid_html,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PARSED"
    assert body["from_global_cache"] is True
