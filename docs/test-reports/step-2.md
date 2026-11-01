# Step 2 Test Report: Multi-Model LLM Gateway, BYOK & Guardrails

**Verdict:** `PASS`

## Summary Table

| Layer / Check | Command | Result | Evidence |
|---|---|---|---|
| Static — Lint | `ruff check .` | PASS | `All checks passed!` |
| Static — Format | `ruff format --check .` | PASS | `45 files already formatted` |
| Static — Types | `mypy src` | PASS | `Success: no issues found in 26 source files` |
| Safety — 20 Seeded Secret Prompts & Log Redaction | `pytest tests/safety/test_pii_and_risk_guardrails.py -q` | PASS | `22 passed` (all 20 seeded PII/API key/password prompts redacted, log filter verified, `@tool(risk=R3)` blocks missing/forged/mismatched tokens) |
| Unit — Validator Retries, BYOK, UI Rate-Limit Error & Budget Guard | `pytest tests/unit/test_llm_gateway.py -q` | PASS | `7 passed` (retries 2 times then raises `StructuredOutputError`, succeeds on retry 2, `TokenBudgetGuard` trips at ceiling, role routing verified, BYOK + fallback verified, `RateLimitExceededError` & `MissingAPIKeyError` carry `ui_action="CHANGE_API_KEY"`) |
| Live — Real Groq API Calls Across All 4 Model Families | `pytest tests/live/test_groq_live.py -m live -v` | PASS | `4 passed in 4.09s` (`openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `allam-2-7b` all returned valid Pydantic-validated `_LiveJobExtract` objects) |
| Universal Gate | `bash .agent/skills/mint-tester/scripts/run_gate.sh` | PASS | `46 passed, 4 deselected in 3.28s`, `93%` total coverage (`814/876`) |
| Mutation Spot-Check | Removed email redaction regex from `pii_shield.py` | PASS | `test_pii_shield_removes_all_20_seeded_secrets` failed immediately (`AssertionError`), restored and re-verified green |

## Live LLM Verification Output (Verbatim)

```text
tests/live/test_groq_live.py::test_live_groq_all_agent_roles_structured[lightweight_parser] PASSED [ 25%]
tests/live/test_groq_live.py::test_live_groq_all_agent_roles_structured[analytical_reasoner] PASSED [ 50%]
tests/live/test_groq_live.py::test_live_groq_all_agent_roles_structured[search_synthesizer] PASSED [ 75%]
tests/live/test_groq_live.py::test_live_groq_all_agent_roles_structured[people_ranker] PASSED [100%]

============================== 4 passed in 4.09s ==============================
```
