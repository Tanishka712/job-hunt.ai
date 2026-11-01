# Step 1 Test Report: Storage Ports, Fakes, Cross-User Caches & Azure Adapters

**Verdict:** `PASS`

## Summary Table

| Layer / Check | Command | Result | Evidence |
|---|---|---|---|
| Static — Lint | `ruff check .` | PASS | `All checks passed!` |
| Static — Format | `ruff format --check .` | PASS | `30 files already formatted` |
| Static — Types | `mypy src` | PASS | `Success: no issues found in 17 source files` |
| Contract Tests (Fakes & Azure Wrappers) | `pytest tests/contract -q` | PASS | `12 passed` (Profile, JobHash 30d TTL, GlobalJobCache 30d TTL, CompanyBriefCache 7d TTL, ApplicationRepo, ThreadStore, AgentSessionStore ETag concurrency, OutreachLogRepo, BlobStore read-only expiring SAS, VectorStore search, idempotent seed, Cosmos/Blob/Search adapters) |
| Safety Tests | `pytest tests/safety -q` | PASS | `3 passed` (forbids password/secret fields in `UserProfile`, multi-user isolation across `VectorStore`/`JobHashRepo`/`ApplicationRepo`/`OutreachLogRepo`, AST import purity check on `ports/storage.py`) |
| Universal Gate | `bash .agent/skills/mint-tester/scripts/run_gate.sh` | PASS | `17 passed in 2.81s`, `97%` total statement coverage (`552/567`) |
| Mutation Spot-Check | Removed `if uid != user_id: continue` in `InMemoryVectorStore.search` | PASS | `test_multi_user_isolation_across_repos` failed immediately (`AssertionError`), restored and re-verified green |

## Command Output (Verbatim)

```text
== ruff ==
All checks passed!
30 files already formatted
== mypy ==
Success: no issues found in 17 source files
== pytest (unit, contract, safety, eval; no live/integration/e2e) ==
.................                                                        [100%]
=============================== tests coverage ================================
Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
src\app\__init__.py                           0      0   100%
src\app\adapters\__init__.py                  0      0   100%
src\app\adapters\blob\__init__.py             0      0   100%
src\app\adapters\blob\store.py               21      0   100%
src\app\adapters\cosmos\__init__.py           0      0   100%
src\app\adapters\cosmos\repos.py            186      9    95%   65, 97, 139, 183, 214, 249, 278, 305, 362
src\app\adapters\fakes\__init__.py            0      0   100%
src\app\adapters\fakes\storage.py           193      6    97%   102, 134, 201, 218, 274, 289
src\app\adapters\search\__init__.py           0      0   100%
src\app\adapters\search\vector_store.py      21      0   100%
src\app\core\__init__.py                      0      0   100%
src\app\core\container.py                    17      0   100%
src\app\core\seed.py                         14      0   100%
src\app\core\settings.py                      9      0   100%
src\app\main.py                              10      0   100%
src\app\ports\__init__.py                     0      0   100%
src\app\ports\storage.py                     96      0   100%
-----------------------------------------------------------------------
TOTAL                                       567     15    97%
Coverage XML written to file test-results/coverage.xml
17 passed, 1 warning in 2.81s
GATE: PASS
```
