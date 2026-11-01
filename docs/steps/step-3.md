# Step S3: Job Finder LLM Agent, Match Scorer & Global Job Cache

## Goal
Build the first real MINT agent (`S3: Job Finder`), combining the `R1_READ_EXTERNAL` `scrape_job` tool (`httpx` + `robots.txt` check + HTML/JSON-LD cleaner $\le 750$ tokens) with the `LIGHTWEIGHT_PARSER` Groq role (`openai/gpt-oss-20b`, fallback `allam-2-7b`) to extract a validated `JobSpec`, reuse public parses across users via `GlobalJobCacheRepo`, deduplicate per user via `JobHashRepo` (30-day TTL), compute a CV `match_score` (0–100), and expose `POST /jobs/ingest`, `POST /jobs/ingest-batch`, and the `job-finder` CLI subcommand.

## Risk Level
- **`R1` (`Risk.R1_READ_EXTERNAL`)**: `scrape_job` reads public job pages after checking `robots.txt`. It has zero write access to any repository.
- Internal storage writes (`GlobalJobCacheRepo`, `JobHashRepo`, `ApplicationRepo`) occur inside the graph coordinator only after a valid `JobSpec` is verified.

## One LLM + One Tool Added
1. **Tool**: `scrape_job(url)` decorated with `@tool("scrape_job", risk=Risk.R1_READ_EXTERNAL)` in `src/app/agents/job_finder/tools.py`.
   - Checks `<origin>/robots.txt` before fetching.
   - Extracts JSON-LD `JobPosting` metadata (if present) and strips `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>`, `<svg>`, and boilerplate HTML down to $\le 750$ tokens (~3,000 characters).
2. **LLM Node**: `LIGHTWEIGHT_PARSER` (`openai/gpt-oss-20b` $\to$ fallback `allam-2-7b`) using `JOB_FINDER_EXTRACT_V1` in `src/app/agents/job_finder/prompts.py` and validated via `llm.complete_structured(..., schema=JobSpec, role=AgentRole.LIGHTWEIGHT_PARSER, retries=2)`.

## Data Touched
- `GlobalJobCacheRepo` (`global_jobs`): caches parsed `JobSpec` by normalized URL for 30 days so multiple users ingesting the same job URL consume 0 extra LLM tokens.
- `JobHashRepo` (`job_hashes`, `/user_id`): stores normalized `compute_job_hash(company, title)` with 30-day TTL only after a successful parse.
- `VectorStore` (`master-cv-chunks`) & `ProfileRepo` (`profile`): read-only lookup to score the `JobSpec` against the user's CV (`match_score` 0–100).
- `ApplicationRepo` (`applications`, `/user_id`): records `ApplicationRecord(status=ApplicationStatus.FETCHED, match_score=...)` for non-duplicate valid jobs.

## Acceptance Tests
1. **HTML Fixtures (`tests/fixtures/jobs/`)**:
   - `valid_job.html`: parses into `JobSpec`, computes `match_score`, writes hash to `JobHashRepo` and record to `ApplicationRepo`.
   - `malformed_job.html`: broken markup is cleaned and parsed cleanly.
   - `non_job_page.html`: identified as `NON_JOB` (`is_job_posting=False` or empty title/company) and does not pollute `JobHashRepo`.
   - `prompt_injection_job.html`: hostile instructions embedded in HTML do not leak profile secrets or bypass tool boundaries.
2. **Deduplication & Cross-User Cache**:
   - Second ingest of the same job by the *same* user returns `DUPLICATE`.
   - Second ingest of the same URL by a *different* user hits `GlobalJobCacheRepo` (0 extra LLM calls) and still computes User B's own `match_score` and `ApplicationRecord`.
3. **Failure Injection**:
   - Schema validation failure retries twice (3 attempts total) then returns `status=FAILED` with `error_reason` without writing to `JobHashRepo`.
   - `robots.txt` disallow returns `status=FAILED` with `error_reason="Disallowed by robots.txt"`.
4. **Safety & Golden Eval**:
   - `scrape_job.risk == Risk.R1_READ_EXTERNAL`.
   - 5 golden job fixtures evaluated in `tests/eval/job_finder/test_golden_jobs.py`.

## Out of Scope
- Tailoring resumes (`S4`), finding contacts (`S5`), company web research (`S6`), drafting outreach emails (`S7`), or submitting applications (`S10`–`S11`).
