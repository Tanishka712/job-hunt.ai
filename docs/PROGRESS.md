# Build Progress

| Step | Name | Risk | Status | Gate evidence | Deployed |
|---|---|---|---|---|---|
| S0 | Skeleton + CI/CD | R0 | DONE | `docs/test-reports/step-0.md` (100% cov, PASS) | GitHub CI (`main`) — Azure deferred to S8 |
| S1 | Storage adapters + cross-user caches | R0-R2 | DONE | `docs/test-reports/step-1.md` (97% cov, 17/17 PASS) | GitHub CI (`main`) — Azure deferred to S8 |
| S2 | Multi-model & multi-key LLM gateway + guardrails | R1 | IN_PROGRESS | | |
| S3 | Job Finder LLM agent + match scorer | R1 | TODO | | |
| S4 | Resume Customizer agent (own memory) | R2 | TODO | | |
| S5 | Networker agent | R1 | TODO | | |
| S6 | Company Research agent | R1 | TODO | | |
| S7 | Email Customizer / Outreach agent (own memory) | R2 | TODO | | |
| S8 | DAG integration + HITL gate | R2 | TODO | | |
| S9 | API contract + UI hookup | R2 | TODO | | |
| S10 | Playwright worker: dry run | R3 (no submit) | TODO | | |
| S11 | Playwright worker: real submit | R3 | TODO | | |
| S12 | Hardening and observability | - | TODO | | |

## Decisions and deviations
1. **Role-Based Multi-Model Routing on Groq (`S2`)**: Groq (`api.groq.com/openai/v1`) serves as the single inference provider, routing each agent role (`AgentRole`) to an independent model family bucket on Groq:
   - `LIGHTWEIGHT_PARSER` (`S3` Job Finder & Intent Routers): `llama-3.1-8b-instant` (overflow: `gemma2-9b-it`)
   - `ANALYTICAL_REASONER` (`S4` Resume Customizer): `openai/gpt-oss-120b` (overflow: `qwen/qwen3-32b`)
   - `PEOPLE_RANKER` (`S5` Networker): `openai/gpt-oss-20b` (overflow: `llama-3.1-8b-instant`)
   - `SEARCH_SYNTHESIZER` (`S6` Company Research): `qwen/qwen3-32b` (overflow: `openai/gpt-oss-20b`)
   - `COPYWRITER` (`S7` Email Outreach Drafter): `llama-3.3-70b-versatile` (overflow: `meta-llama/llama-4-scout-17b-16e-instruct`)
   - `VISION_AUDITOR` (`S10`/`S11` Playwright Form Auditor): `meta-llama/llama-4-scout-17b-16e-instruct`
2. **10 Users x 50 Jobs/Day (500 Jobs/Day) Scaling Architecture**:
   - `S3` always uses its lightweight LLM (`llama-3.1-8b-instant`) to extract structured `JobSpec` fields, while `scrape_job` strips HTML/JSON-LD boilerplate down to ~750 tokens per job (~950 tokens total per LLM parse).
   - Shared public Cosmos caches (`global_jobs` 30-day TTL and `company_briefs` 7-day TTL) avoid re-parsing the same job URL or company across users, while user data (`/user_id`) and sessions (`resume:{user_id}:{job_id}`, `email:{user_id}:{job_id}:{contact_id}`) remain strictly isolated.
   - `S2` includes `GroqKeyPool` (round-robin API key rotation + optional per-user BYOK) and an async token-bucket rate limiter to pace batch runs smoothly.

## Open questions for the user
- `S0` local gate is green (`PASS`, 100% coverage). Say **"next"** to start `S1` (Storage Ports, Fakes & Cross-User Caches), or let me know if you want to push/deploy `S0` to GitHub/Azure first.
