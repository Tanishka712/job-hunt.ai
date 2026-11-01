# Test Report: Step S3 — Job Finder LLM Agent, Match Scorer & Global Job Cache

**Verdict:** `PASS`

## 1. Check Summary Table

| Layer | Command | Result | Evidence |
|---|---|---|---|
| **Static (`ruff`)** | `ruff check . && ruff format --check .` | `PASS` | `All checks passed! 61 files already formatted` |
| **Types (`mypy`)** | `mypy src` | `PASS` | `Success: no issues found in 37 source files` |
| **Unit (`unit`)** | `pytest tests/unit/test_job_finder.py` | `PASS` | `13/13 passed` (HTML cleaner, JSON-LD extraction, hash normalization table, dedupe, cross-user global cache, malformed HTML, non-job page, 2-retry exhaustion, `robots.txt` disallow, FastAPI `/jobs/ingest` & `/jobs/ingest-batch`) |
| **Safety (`safety`)** | `pytest tests/safety/test_job_finder_safety.py` | `PASS` | `2/2 passed` (`scrape_job.risk == Risk.R1_READ_EXTERNAL` with zero storage access; prompt injection HTML fixture shielded and blocked from accessing user profile PII) |
| **Golden Eval (`eval`)** | `pytest tests/eval/job_finder/test_golden_jobs.py` | `PASS` | `5/5 passed` (5 golden job postings scored deterministically against seeded CV chunks) |
| **Mutation Spot-Check** | Disabled `job_hash_repo.exists` check in `src/app/agents/job_finder/graph.py` | `PASS` | `test_job_finder_duplicate_dropped_for_same_user` turned `FAILED` (`AssertionError: assert PARSED == DUPLICATE`), then restored to green |
| **Live Groq CLI (`live`)** | `python -m app.cli job-finder tests/fixtures/jobs/valid_job.html` & `non_job_page.html` | `PASS` | Live `openai/gpt-oss-20b` extracted full `JobSpec` (`match_score=100.0%`) on `valid_job.html` and returned `NON_JOB` on `non_job_page.html` |
| **Full Gate** | `bash .agent/skills/mint-tester/scripts/run_gate.sh` | `PASS` | `71 passed, 4 deselected in 4.57s` (89% total coverage) |

## 2. Reproduce Commands
```powershell
& "C:\Program Files\Git\bin\bash.exe" .agent/skills/mint-tester/scripts/run_gate.sh
.\.venv\Scripts\python.exe -m app.cli job-finder tests/fixtures/jobs/valid_job.html
.\.venv\Scripts\python.exe -m app.cli job-finder tests/fixtures/jobs/non_job_page.html
```
