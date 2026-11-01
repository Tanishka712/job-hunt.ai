# Build Progress

| Step | Name | Risk | Status | Gate evidence | Deployed |
|---|---|---|---|---|---|
| S0 | Skeleton + CI/CD | R0 | DONE | `docs/test-reports/step-0.md` (100% cov, PASS) | GitHub CI (`main`) — Azure deferred to S8 |
| S1 | Storage adapters + cross-user caches | R0-R2 | DONE | `docs/test-reports/step-1.md` (97% cov, 17/17 PASS) | GitHub CI (`main`) — Azure deferred to S8 |
| S2 | Multi-model LLM gateway, BYOK + guardrails | R1 | DONE | `docs/test-reports/step-2.md` (93% cov, 46/46 PASS + 4/4 Live Groq PASS) | GitHub CI (`main`) — Azure deferred to S8 |
| S3 | Job Finder LLM agent + match scorer | R1 | DONE | `docs/test-reports/step-3.md` (89% cov, 71/71 PASS + Live CLI PASS) | GitHub CI (`main`) — Azure deferred to S8 |
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
1. **Role-Based Multi-Model Routing & Role System Prompts on Groq (`S2`)**: Groq (`api.groq.com/openai/v1`) routes each agent role (`AgentRole`) to an independent live-verified model family bucket on Groq, with a domain-bounded system prompt (`ROLE_SYSTEM_PROMPTS`) injected automatically:
   - `LIGHTWEIGHT_PARSER` (`S3` Job Finder & Intent Routers): `openai/gpt-oss-20b` (fallback: `allam-2-7b` [7,000 RPD])
   - `ANALYTICAL_REASONER` (`S4` Resume Customizer): `openai/gpt-oss-120b` (fallback: `qwen/qwen3.8-27b`)
   - `PEOPLE_RANKER` (`S5` Networker): `allam-2-7b` (fallback: `openai/gpt-oss-20b`)
   - `SEARCH_SYNTHESIZER` (`S6` Company Research): `qwen/qwen3.8-27b` (fallback: `openai/gpt-oss-20b`)
   - `COPYWRITER` (`S7` Email Outreach Drafter): `openai/gpt-oss-120b` (fallback: `qwen/qwen3.8-27b`)
   - `VISION_AUDITOR` (`S10`/`S11` Playwright Form Auditor): `qwen/qwen3.8-27b` (fallback: `openai/gpt-oss-20b`)
2. **Per-User BYOK & Explicit Rate-Limit UI Error (`S2`)**: Single default key + per-user BYOK (`user_api_key`). When Groq returns `429`, `GroqAdapter` raises `RateLimitExceededError` with `ui_action = "CHANGE_API_KEY"`.
3. **Cross-User Global Job Cache + HTML Cleaner (`S3`)**: `scrape_job` (`Risk.R1_READ_EXTERNAL`) checks `robots.txt`, extracts JSON-LD `JobPosting` metadata, and strips HTML noise to $\le 3,000$ chars (~750 tokens). Parsed `JobSpec`s are cached in `GlobalJobCacheRepo` by normalized URL for 30 days so multiple users ingesting the same job URL consume 0 extra LLM tokens.
4. **Azure Provisioning Deferred to `S8`**: Preserves Azure for Students credit during `S0`–`S7` development while GitHub Actions CI runs on every push to `https://github.com/Tanishka712/job-hunt.ai`.

## Open questions for the user
- `S3` is complete and verified against live Groq (`71/71 PASSED`). Test via CLI and say **"proceed with s4"** to start `S4` (Resume Customizer Agent with isolated conversational memory, truthfulness verifier, and PDF renderer).
