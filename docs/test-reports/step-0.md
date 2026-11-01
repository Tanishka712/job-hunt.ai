# Step 0 Test Report: Skeleton + CI/CD

**Verdict:** `PASS`

## Summary Table

| Layer / Check | Command | Result | Evidence |
|---|---|---|---|
| Static — Lint | `ruff check .` | PASS | `All checks passed!` |
| Static — Format | `ruff format --check .` | PASS | `10 files already formatted` |
| Static — Types | `mypy src` | PASS | `Success: no issues found in 4 source files` |
| Unit Tests | `pytest -m "not live and not integration and not e2e" --cov=src` | PASS | `2 passed in 2.25s`, `100%` coverage (`19/19` statements) |
| Mutation Spot-Check | Mutated `/health` response to `{"status": "broken"}` | PASS | Test failed as expected (`AssertionError: assert 'broken' == 'ok'`), restored and re-verified green |

## Command Output (Verbatim)

```text
== ruff ==
All checks passed!
10 files already formatted
== mypy ==
Success: no issues found in 4 source files
== pytest (unit, contract, safety, eval; no live/integration/e2e) ==
..                                                                       [100%]
=============================== tests coverage ================================
Name                       Stmts   Miss  Cover   Missing
--------------------------------------------------------
src\app\__init__.py            0      0   100%
src\app\core\__init__.py       0      0   100%
src\app\core\settings.py       9      0   100%
src\app\main.py               10      0   100%
--------------------------------------------------------
TOTAL                         19      0   100%
Coverage XML written to file test-results/coverage.xml
2 passed, 1 warning in 2.25s
GATE: PASS
```
