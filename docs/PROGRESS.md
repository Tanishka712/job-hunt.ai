# Build Progress

| Step | Name | Risk | Status | Gate evidence | Deployed |
|---|---|---|---|---|---|
| S0 | Skeleton + CI/CD | R0 | DONE | `docs/test-reports/step-0.md` (100% cov, PASS) | GitHub CI (`main`) — Azure deferred to S8 |
| S1 | Storage adapters + cross-user caches | R0-R2 | DONE | `docs/test-reports/step-1.md` (97% cov, 17/17 PASS) | GitHub CI (`main`) — Azure deferred to S8 |
| S2 | Multi-model LLM gateway, BYOK + guardrails | R1 | DONE | `docs/test-reports/step-2.md` (93% cov, 46/46 PASS + 4/4 Live Groq PASS) | GitHub CI (`main`) — Azure deferred to S8 |
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
1. **Role-Based Multi-Model Routing on Groq (`S2`)**: Groq (`api.groq.com/openai/v1`) routes each agent role (`AgentRole`) to an independent live-verified model family bucket on Groq:
   - `LIGHTWEIGHT_PARSER` (`S3` Job Finder & Intent Routers): `openai/gpt-oss-20b` (fallback: `allam-2-7b` [7,000 RPD])
   - `ANALYTICAL_REASONER` (`S4` Resume Customizer): `openai/gpt-oss-120b` (fallback: `qwen/qwen3.8-27b`)
   - `PEOPLE_RANKER` (`S5` Networker): `allam-2-7b` (fallback: `openai/gpt-oss-20b`)
   - `SEARCH_SYNTHESIZER` (`S6` Company Research): `qwen/qwen3.8-27b` (fallback: `openai/gpt-oss-20b`)
   - `COPYWRITER` (`S7` Email Outreach Drafter): `openai/gpt-oss-120b` (fallback: `qwen/qwen3.8-27b`)
   - `VISION_AUDITOR` (`S10`/`S11` Playwright Form Auditor): `qwen/qwen3.8-27b` (fallback: `openai/gpt-oss-20b`)
2. **Per-User BYOK & Explicit Rate-Limit UI Error (`S2`)**: Removed round-robin key rotation in favor of a single default key + per-user BYOK (`user_api_key`). When Groq returns `429`, `GroqAdapter` raises `RateLimitExceededError` with `ui_action = "CHANGE_API_KEY"` and `retry_after_seconds` so the UI clearly prompts the user to enter/change their Groq API key.
3. **Azure Provisioning Deferred to `S8`**: Preserves Azure for Students credit during `S0`–`S7` development while GitHub Actions CI runs on every push to `https://github.com/Tanishka712/job-hunt.ai`.

## Open questions for the user
- `S2` is complete and tested against all 4 live Groq models (`4/4 PASSED`). Say **"next"** to start `S3` (Job Finder LLM Agent + Match Scorer).
