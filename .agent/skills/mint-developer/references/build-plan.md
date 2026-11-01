# MINT Build Plan

Order is by **risk**, lowest first, and by **dependency**. Each step adds one capability, is tested, pushed to GitHub, built and deployed by Azure Pipelines, and only then do we move on.

Risk ladder: **R0** pure logic, **R1** read-only external call, **R2** writes to our own storage, **R3** side effect in the outside world.

Every step's exit gate = tester gate green (see `mint-tester`) + pipeline green + deployed to staging + smoke test + PROGRESS.md updated.

## Contents
S0 Skeleton + CI/CD · S1 Storage adapters · S2 LLM gateway + guardrails · S3 Job Finder · S4 Resume Customizer · S5 Networker · S6 Company Research · S7 Email Customizer · S8 DAG + HITL · S9 API/UI hookup · S10 Playwright dry run · S11 Playwright real submit · S12 Hardening

---

## S0: Skeleton + CI/CD (R0)
**Goal:** Prove the delivery path before any agent exists: GitHub → GitHub Actions → Azure Container Apps, with webhook notifications to Azure DevOps.
**Build:** Python 3.11 project (`pyproject.toml`, `src/app`, `tests/`), FastAPI with `GET /health` and `GET /version`, Dockerfile, `.github/workflows/ci-cd.yml` (lint, mypy, pytest, Docker build/push, deploy to staging Container App, webhook to Azure DevOps), ruff + mypy + pytest config, pytest markers (`unit`, `contract`, `integration`, `live`, `safety`).
**Tests:** `/health` returns 200 and the git SHA; lint/type/test commands pass in GitHub Actions; Azure DevOps receives the webhook event.
**Exit:** merge to `main` deploys a hello-world image to staging, smoke test hits the public URL, deployment logged in Azure DevOps.
**Out of scope:** any LLM, any database.

## S1: Storage adapters (R0 → R2 internal)
**Goal:** All persistence behind ports, with in-memory fakes and real Azure adapters.
**Build:** ports `ProfileRepo`, `JobHashRepo`, `ApplicationRepo`, `ThreadStore`, `AgentSessionStore`, `OutreachLogRepo`, `BlobStore`, `VectorStore`. Fakes for each. Cosmos adapters (containers in `architecture.md`), Blob adapter with SAS URL helper, AI Search adapter. A seed script that loads the master profile into Cosmos, master resume into Blob, and chunked master CV into the vector index.
**Tests:** one **contract test suite** per port, run against both the fake and the real adapter (real ones marked `integration`). TTL test: job-hash container has `defaultTtl` = 30 days and items expire (verify config; do not wait 30 days). Vector search returns the expected chunk for a known query.
**Exit:** `integration` tests pass against the dev Azure resources from the pipeline's integration stage.
**Out of scope:** LLMs.

## S2: LLM gateway + guardrails (R1)
**Goal:** The single safe door to any model.
**Build:** `LLMClient` port; Groq adapter as primary provider with dual-tier routing:
  - Fast tier: Groq `llama-3.1-8b-instant` (parsing, search, summarization, fast verifier checks).
  - Reasoning tier: Groq `llama-3.3-70b-versatile` (resume synthesis, outreach drafting).
  - Vision tier: Groq `llama-3.2-11b-vision-preview` (screenshot audits).
  - Fallback / testing: `FakeLLM` and rate-limit retry logic.
Guardrails: PII/credential shield (redacts emails, phones, tokens, anything tagged secret before an external call), structured-output validator (Pydantic, max 2 retries, then typed error), token budget + rate limiter with fallback to the cheap model, request/response tracing with redaction.
**Tests:** shield removes seeded secrets from 20 sample prompts; validator retries exactly twice then raises; budget guard trips at the limit; fallback is used when the primary errors (simulate with fake). One `live` smoke test per provider.
**Out of scope:** agents, tools.

## S3: Job Finder agent (R1) — first real agent
**MINT unit:** cheap LLM + `scrape_job` tool (httpx + BeautifulSoup).
**Build:** LangGraph graph: `fetch → parse (LLM → JobSpec) → dedupe (hash = normalized company + title) → verify`. Dedupe hit drops the job and ends the run. Hash written to Cosmos with 30-day TTL only after a successful parse.
**Tests:** saved HTML fixtures (no live web in CI), including malformed pages; duplicate job is dropped; schema failure retries twice then marks the run failed with a reason; robots.txt respected; scrape tool is R1 and cannot write anywhere.
**Exit:** staging endpoint `POST /jobs/ingest {url}` returns a `JobSpec` or `DUPLICATE`.
**Note:** scrape only sources whose terms allow it. Prefer official job APIs/RSS where they exist.

## S4: Resume Customizer agent (R2) — own state + conversational memory
**MINT unit:** reasoning LLM + `search_master_cv` vector tool; then a render tool (Markdown → PDF, LaTeX optional) writing to Blob.
**Build:** see `agent-memory.md`. Graph: `load_session → retrieve chunks → draft → verify truthfulness → render → save version`. Refinement graph: `interpret feedback → revise → verify → save version`, with revert and compare.
**Tests:** every bullet cites a retrieved chunk id (inject a fake LLM that invents a claim → verifier rejects); iteration 3 respects an instruction given in iteration 1 (pinned preferences); revert restores a previous version byte-for-byte; session isolation (editing job A never changes job B); email-agent state is untouchable from this agent (import boundary test).
**Exit:** `POST /jobs/{id}/resume`, `POST /jobs/{id}/resume/refine`, `GET /jobs/{id}/resume/versions`, `POST /jobs/{id}/resume/revert`.

## S5: Networker agent (R1)
**MINT unit:** cheap LLM + `search_people` tool (DuckDuckGo/Serper; LinkedIn only through compliant means).
**Build:** query generation from `JobSpec` → candidate profiles → ranking → `ContactList`. Consults `OutreachLogRepo` so the same recruiter is never suggested twice.
**Tests:** fixtures for search results; ranking is deterministic given fixtures; previously contacted person is excluded; output contains no personal data beyond what the source published.

## S6: Company Research agent (R1)
**MINT unit:** cheap LLM + `web_search` tool → `CompanyBrief` (tech stack, recent news, culture notes).
**Tests:** fixtures; brief schema; every claim carries a source URL; empty search result produces a "no data" brief rather than invention.

## S7: Email Customizer / Outreach agent (R2) — own state + conversational memory
**MINT unit:** reasoning LLM + template retrieval tool (semantic memory) + cheap heuristic verifier.
**Build:** separate from the Resume agent (own state schema, own session id, own versions). Input is the typed handoff `JobContext + Contact + ResumeArtifact summary + CompanyBrief`. Verifier: word count < 150, clear CTA, no PII leak, no claim absent from the resume summary. Refinement loop like S4. The agent drafts only; it has no send tool.
**Tests:** as S4, plus the verifier fails a 200-word draft and a draft without a CTA; draft regenerates at most N times then escalates to the user.

## S8: DAG integration + HITL gate (R2)
**Goal:** Wire the proven agents; still no outside side effects.
**Build:** LangGraph DAG: Job Finder → parallel `asyncio.gather` of Networker, Resume, Company Research → Outreach → **HITL gate**. At the gate, the thread status becomes `AWAITING_APPROVAL` and the checkpoint is written to Cosmos. `POST /approve` requires an HMAC-signed payload that names the exact contact, resume version, and email version approved. Event published to a queue on approval (the queue consumer does not exist yet).
**Tests:** one branch failing does not cancel the others and the run degrades gracefully; checkpoint survives process restart (kill and resume); approving a stale version is rejected; any R3 tool call without a valid approval token raises (`safety` marker); idempotent approve (double-click produces one event).

## S9: API contract + UI hookup (R2)
**Build:** freeze the OpenAPI spec, SSE stream for run progress, endpoints for the iterative refine chats. Build the UI against the user's design instructions (ask for them when you reach this step) on Azure Static Web Apps.
**Tests:** contract tests generated from OpenAPI; SSE event ordering; CORS limited to the SWA origin; basic e2e (Playwright test against staging, using the fake worker).

## S10: Playwright worker, dry run (R3, submit disabled)
**Build:** Container Apps Job consuming the approval queue. Downloads the tailored PDF via short-lived SAS, opens the target form, fills fields from the profile, **never clicks submit**, saves screenshots to Blob, reports `DRY_RUN_OK` / `DRY_RUN_FAILED`.
**Tests:** run against a local fixture form served inside the test; selector-mapping tests; screenshot saved on failure; the submit click is physically absent in this build (feature flag off, asserted in a test).

## S11: Playwright worker, real submit (R3)
**Build:** enable submit behind a flag and a per-application confirmation. Post-execution verification loop (confirmation text/URL), writes `APPLIED` to Cosmos only on verified success, screenshot + dashboard alert otherwise. Global kill switch and daily application cap.
**Tests:** sandbox form first; then exactly one real, user-chosen application with the user watching. Kill switch halts an in-flight run.
**Note:** many sites prohibit automated submission or use bot detection/CAPTCHA. Do not bypass CAPTCHAs or anti-bot controls; fall back to "ready to submit manually" with the prepared materials.

## S12: Hardening
Observability (structured logs, trace per run, cost per run), retention rules, load test of the DAG, backup/restore drill for Cosmos, runbook in `docs/runbook.md`.
