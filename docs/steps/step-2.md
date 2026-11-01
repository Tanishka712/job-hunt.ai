# Step 2: Multi-Model LLM Gateway, BYOK & Guardrails

**Risk level:** R1 (read-only external LLM call; no external writes)   **Depends on:** S1
**New capability (one LLM + one tool):** `LLMClient` port (`AgentRole` routing across 4 active Groq model buckets), `GroqAdapter` with per-user BYOK (`user_api_key`) and explicit `RateLimitExceededError` / `MissingAPIKeyError` (`ui_action = "CHANGE_API_KEY"`) for the UI, `FakeLLM`, PII/credential shield (`shield`), Pydantic structured validator (`call_structured`, max 2 retries), token budget & async TPM pacer (`TokenBudgetGuard`), and `@tool(name, risk=...)` R3 approval gate decorator.
**Data touched (read / write):** Reads `GROQ_API_KEY` from `Settings` (or per-user `user_api_key`). No database writes.
**Acceptance tests:**
- [x] `shield()` strips seeded secrets (emails, phones, API keys, Bearer tokens, passwords) from 20 sample prompts.
- [x] Captured logs contain zero secrets even when prompts contain seeded tokens/emails.
- [x] `call_structured()` retries exactly twice (3 attempts total) with validation feedback, then raises `StructuredOutputError`.
- [x] `TokenBudgetGuard` trips `BudgetExceededError` when run or daily token limit is exceeded.
- [x] `GroqAdapter` routes each `AgentRole` (`LIGHTWEIGHT_PARSER` -> `openai/gpt-oss-20b`, `ANALYTICAL_REASONER` -> `openai/gpt-oss-120b`, `PEOPLE_RANKER` -> `allam-2-7b`, `SEARCH_SYNTHESIZER` -> `qwen/qwen3.8-27b`, `COPYWRITER` -> `openai/gpt-oss-120b`, `VISION_AUDITOR` -> `qwen/qwen3.8-27b`), supports per-user BYOK (`user_api_key`), falls back to the secondary model on 5xx, and raises `RateLimitExceededError` (`ui_action="CHANGE_API_KEY"`) when rate limits (`429`) are hit.
- [x] Every `@tool(..., risk=Risk.R3_SIDE_EFFECT)` raises `ApprovalRequiredError` without a valid HMAC-signed `ApprovalToken`.
- [x] `@pytest.mark.live` suite tests all 4 Groq models (`openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `allam-2-7b`) with real live LLM calls.
**Out of scope:** Domain agents (`S3`–`S7`) and web scraping tools.
**Rollback:** Revert branch or point composition root to `FakeLLM`.
