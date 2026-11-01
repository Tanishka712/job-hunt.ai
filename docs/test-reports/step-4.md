# Test Report: Step S4 — Resume Customizer Agent (Own State, Conversational Memory, Verifier & PDF Renderer)

**Verdict:** `PASS`

## 1. Check Summary Table

| Layer | Command | Result | Evidence |
|---|---|---|---|
| **Static (`ruff`)** | `ruff check . && ruff format --check .` | `PASS` | `All checks passed! 75 files already formatted` |
| **Types (`mypy`)** | `mypy src` | `PASS` | `Success: no issues found in 46 source files` |
| **Unit (`unit`)** | `pytest tests/unit/test_resume_agent.py` | `PASS` | `6/6 passed` (initial draft + 1-page PDF verification, invented claim/unknown chunk ID rejection, pinned preference persistence across turns, byte-exact revert + unified diff compare with 0 LLM calls, per-job session isolation, FastAPI `/jobs/{id}/resume/*` endpoints) |
| **Safety (`safety`)** | `pytest tests/safety/test_agent_isolation.py` | `PASS` | `2/2 passed` (AST import boundary confirms `app.agents.resume` never imports `app.agents.email`; `ResumeState` rejects non-`resume:` session IDs) |
| **Golden Eval (`eval`)** | `pytest tests/eval/resume/test_golden_resumes.py` | `PASS` | `5/5 passed` (5 golden resume tailoring cases verified for truthfulness, chunk citations, and 1-page PDF budget) |
| **Mutation Spot-Check** | Disabled chunk ID & invented metric checks in `src/app/agents/resume/verifier.py` | `PASS` | `test_verifier_rejects_invented_claim_and_creates_no_version_on_exhaustion` turned `FAILED` (`AssertionError: assert True is False`), then restored to green |
| **Live Groq CLI (`live`)** | `python -m app.cli resume "Senior AI Platform Engineer..." --refine "Never mention Kubernetes and highlight Azure AI Search"` | `PASS` | Live `openai/gpt-oss-120b` drafted `v1` citing `['cli-user-chunk-1', 'cli-user-chunk-2']` and refined to `v2` removing `"Kubernetes"` and highlighting `"Azure AI Search"` |
| **Full Gate** | `bash .agent/skills/mint-tester/scripts/run_gate.sh` | `PASS` | `85 passed, 4 deselected in 5.35s` (89% total coverage) |

## 2. Reproduce Commands
```powershell
& "C:\Program Files\Git\bin\bash.exe" .agent/skills/mint-tester/scripts/run_gate.sh
.\.venv\Scripts\python.exe -m app.cli resume "Senior AI Platform Engineer at Acme (Python, FastAPI, LangGraph, Azure Cosmos DB)" --refine "Never mention Kubernetes and highlight Azure AI Search"
```
