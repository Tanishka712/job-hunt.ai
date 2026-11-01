"""Unit tests for the MINT interactive CLI (`src/app/cli.py`)."""

import pytest

from app.adapters.fakes.llm import FakeLLM
from app.adapters.llm.groq_adapter import (
    GroqAdapter,
    GroqTransportResponse,
)
from app.cli import async_main
from app.ports.llm import AgentRole


@pytest.mark.unit
async def test_cli_roles_and_shield_commands(capsys: pytest.CaptureFixture[str]) -> None:
    """`roles` prints model table; `shield` redacts PII and secrets."""
    code = await async_main(["roles"])
    assert code == 0
    out = capsys.readouterr().out
    assert "lightweight_parser" in out
    assert "openai/gpt-oss-120b" in out

    code = await async_main(["shield", "Email me at secret.user@example.com"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Had secret/PII : True" in out
    assert "[REDACTED_EMAIL]" in out
    assert "secret.user@example.com" not in out


@pytest.mark.unit
async def test_cli_prompt_and_extract_commands(capsys: pytest.CaptureFixture[str]) -> None:
    """`prompt` and `extract` route through shield + LLMClient and format output."""
    fake_llm = FakeLLM(
        scripted_responses=[
            "Hello from fake LLM!",
            (
                '{"title": "AI Engineer", "company": "Acme", '
                '"location": "Remote", "required_skills": ["Python", "LangGraph"], '
                '"summary": "Build multi-agent systems"}'
            ),
        ]
    )

    code = await async_main(
        ["prompt", "Hi from user@example.com", "--role", "analytical_reasoner"],
        llm_override=fake_llm,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "[REDACTED_EMAIL]" in out
    assert "Hello from fake LLM!" in out
    assert fake_llm.calls[0].role is AgentRole.ANALYTICAL_REASONER

    code = await async_main(
        ["extract", "Acme is hiring an AI Engineer with Python and LangGraph."],
        llm_override=fake_llm,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert '"company": "Acme"' in out
    assert '"LangGraph"' in out


@pytest.mark.unit
async def test_cli_surfaces_rate_limit_ui_action(capsys: pytest.CaptureFixture[str]) -> None:
    """When rate limits are hit, CLI prints `[UI Action: CHANGE_API_KEY]` and exits with code 2."""

    async def rate_limited_transport(
        api_key: str, model: str, messages: list[dict[str, object]], json_mode: bool
    ) -> GroqTransportResponse:
        return GroqTransportResponse(status_code=429, content="Rate limit", retry_after_seconds=30)

    adapter = GroqAdapter(default_api_key="test-key", transport=rate_limited_transport)
    code = await async_main(["prompt", "Test rate limit"], llm_override=adapter)
    assert code == 2
    err = capsys.readouterr().err
    assert "[UI Action: CHANGE_API_KEY]" in err


@pytest.mark.unit
async def test_cli_job_finder_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """`job-finder` CLI command runs S3 Job Finder on inline text and outputs JobSpec + CV score."""
    fake_llm = FakeLLM(
        scripted_responses=[
            """{
                "title": "Senior AI Engineer",
                "company": "Acme AI",
                "location": "Remote",
                "remote_policy": "remote",
                "seniority": "senior",
                "required_skills": ["Python", "FastAPI", "LangGraph"],
                "nice_to_have_skills": [],
                "responsibilities": ["Build agents"],
                "salary_range": "",
                "source_url": "https://cli.inline/test",
                "is_job_posting": true
            }"""
        ]
    )
    code = await async_main(
        ["job-finder", "Acme AI is hiring a Senior AI Engineer (Python, FastAPI, LangGraph)"],
        llm_override=fake_llm,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "[Status]           PARSED" in out
    assert '"company": "Acme AI"' in out
    assert "[CV Match Score]" in out


@pytest.mark.unit
async def test_cli_resume_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """`resume` CLI command runs S4 Resume Customizer and optional refinement turn."""
    fake_llm = FakeLLM(
        scripted_responses=[
            (
                '{"professional_summary": "Senior AI Engineer skilled in Python and FastAPI.", '
                '"bullets": [{"text": "Architected multi-agent LLM workflows using Python, '
                'FastAPI, and LangGraph.", "source_chunk_ids": ["cli-user-chunk-1"]}], '
                '"highlighted_skills": ["Python", "FastAPI", "LangGraph"]}'
            ),
            (
                '{"intent": "edit", "pinned_instruction_to_add": "Never mention Kubernetes", '
                '"target_version": null, "compare_from_version": null}'
            ),
            (
                '{"professional_summary": "Senior AI Engineer with Azure Cosmos DB.", '
                '"bullets": [{"text": "Designed semantic vector search pipelines on Azure AI '
                'Search and Azure Cosmos DB.", "source_chunk_ids": ["cli-user-chunk-2"]}], '
                '"highlighted_skills": ["Python", "FastAPI", "Azure Cosmos DB"]}'
            ),
        ]
    )
    code = await async_main(
        [
            "resume",
            "Senior AI Platform Engineer",
            "--refine",
            "Focus on Azure Cosmos DB and never mention Kubernetes",
        ],
        llm_override=fake_llm,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "[Version]          v1" in out
    assert "[Verifier Passed]  True" in out
    assert "[Active Version]   v2" in out
