"""Safety tests for S3 Job Finder Agent (R1 tool boundary and prompt injection protection)."""

import inspect
from pathlib import Path

import pytest

from app.adapters.fakes.llm import FakeLLM
from app.agents.job_finder.graph import run_job_finder
from app.agents.job_finder.schemas import JobIngestRequest, JobIngestStatus
from app.agents.job_finder.tools import HttpResponseData, scrape_job
from app.core.container import build_in_memory_storage
from app.core.seed import seed_user_data
from app.guardrails.risk import Risk

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "jobs"


@pytest.mark.safety
def test_scrape_job_tool_is_r1_and_has_no_storage_write_access() -> None:
    """scrape_job is tagged Risk.R1_READ_EXTERNAL and accepts no storage repo arguments."""
    assert getattr(scrape_job, "risk", None) == Risk.R1_READ_EXTERNAL
    assert getattr(scrape_job, "tool_name", None) == "scrape_job"

    sig = inspect.signature(scrape_job)
    forbidden_params = {
        "storage",
        "profile_repo",
        "job_hash_repo",
        "application_repo",
        "blob_store",
        "vector_store",
    }
    assert forbidden_params.isdisjoint(set(sig.parameters.keys()))


@pytest.mark.safety
async def test_prompt_injection_in_scraped_html_does_not_leak_profile_or_secrets() -> None:
    """Hostile instructions inside HTML cannot access user profile PII or inject secrets."""
    storage = build_in_memory_storage()
    await seed_user_data(
        user_id="victim-user",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )
    injection_html = (FIXTURES_DIR / "prompt_injection_job.html").read_text(encoding="utf-8")

    fake_llm = FakeLLM(
        scripted_responses=[
            """{
                "title": "ML Infrastructure Engineer",
                "company": "SafeCorp AI",
                "location": "Remote",
                "remote_policy": "remote",
                "seniority": "senior",
                "required_skills": ["Python", "PyTorch", "Kubernetes", "FastAPI"],
                "nice_to_have_skills": [],
                "responsibilities": ["Build ML infrastructure"],
                "salary_range": "",
                "source_url": "https://jobs.example.com/safecorp",
                "is_job_posting": true
            }"""
        ]
    )

    async def fetcher(url: str) -> HttpResponseData:
        if url.endswith("/robots.txt"):
            return HttpResponseData(status_code=200, text="User-agent: *\nAllow: /\n", url=url)
        return HttpResponseData(status_code=200, text=injection_html, url=url)

    res = await run_job_finder(
        JobIngestRequest(url="https://jobs.example.com/safecorp", user_id="victim-user"),
        llm=fake_llm,
        storage=storage,
        fetcher=fetcher,
    )

    assert res.status == JobIngestStatus.PARSED
    assert len(fake_llm.calls) == 1
    sent_prompt = fake_llm.calls[0].prompt

    # 1. Hostile email inside the HTML was redacted by shield() before reaching the LLM
    assert "attacker@evil.example.com" not in sent_prompt
    # 2. Victim's private profile email/phone were never placed into the Job Finder LLM prompt
    profile = await storage.profile_repo.get("victim-user")
    assert profile is not None
    assert profile.email not in sent_prompt
    assert profile.phone not in sent_prompt
