---
description: Run the tester agent against the current step (or a named step) and write a test report.
---

1. Read `docs/PROGRESS.md` to find the current step (or use the step the user named).
2. Use skill **mint-tester**: run `bash .agent/skills/mint-tester/scripts/run_gate.sh`, then the step-specific checks from `build-plan.md`.
3. Write `docs/test-reports/step-N.md` with pass/fail per check, the failing output verbatim, and a diagnosis.
4. If failing, hand the diagnosis to **mint-developer** with the smallest reproducing test.
