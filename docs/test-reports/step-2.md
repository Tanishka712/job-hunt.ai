# Step 2 Test Report: Multi-Model & Multi-Key LLM Gateway, Token Pacer & Guardrails

**Verdict:** `PASS`

## Summary Table

| Layer / Check | Command | Result | Evidence |
|---|---|---|---|
| Static — Lint | `ruff check .` | PASS | `All checks passed!` |
| Static — Format | `ruff format --check .` | PASS | `45 files already formatted` |
| Static — Types | `mypy src` | PASS | `Success: no issues found in 27 source files` |
| Safety — 20 Seeded Secret Prompts & Log Redaction | `pytest tests/safety/test_pii_and_risk_guardrails.py -q` | PASS | `22 passed` (all 20 seeded PII/API key/password prompts redacted, log filter verified, `@tool(risk=R3)` blocks missing/forged/mismatched tokens) |
| Unit — Validator Retries, Key Pool, Role Routing & Budget Guard | `pytest tests/unit/test_llm_gateway.py -q` | PASS | `6 passed` (retries exactly 2 times then raises `StructuredOutputError`, succeeds on retry 2, `TokenBudgetGuard` trips at ceiling, role routing verified, key rotation + fallback verified) |
| Live — Groq Multi-Model Smoke Test | `pytest tests/live/test_groq_live.py -m live -q` | PASS | `1 passed in 1.61s` against live Groq API (`openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `allam-2-7b`) |
| Universal Gate | `bash .agent/skills/mint-tester/scripts/run_gate.sh` | PASS | `45 passed, 1 deselected in 3.47s`, `93%` total coverage (`817/878`) |
| Mutation Spot-Check | Removed email redaction regex from `pii_shield.py` | PASS | `test_pii_shield_removes_all_20_seeded_secrets` failed immediately (`AssertionError`), restored and re-verified green |

## Command Output (Verbatim)

```text
== ruff ==
All checks passed!
45 files already formatted
== mypy ==
Success: no issues found in 27 source files
== pytest (unit, contract, safety, eval; no live/integration/e2e) ==
.............................................                            [100%]
=============================== tests coverage ================================
Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
src\app\adapters\fakes\llm.py                27      4    85%   47-49, 59
src\app\adapters\llm\groq_adapter.py         75     23    69%   39-45, 55-84, 110, 149
src\app\adapters\llm\key_pool.py             30      4    87%   26, 38-40
src\app\guardrails\budget.py                 45     10    78%   48-50, 64-69, 79
src\app\guardrails\pii_shield.py             20      2    90%   74-75
src\app\guardrails\risk.py                   53      0   100%
src\app\guardrails\validator.py              36      1    97%   34
src\app\ports\llm.py                         20      0   100%
-----------------------------------------------------------------------
TOTAL                                       878     61    93%
45 passed, 1 deselected, 1 warning in 3.47s
GATE: PASS
```
