---
description: Push the current step to GitHub, drive Azure Pipelines, deploy to staging, smoke-test, and offer promotion to production.
---

1. Confirm the tester gate is green for the current step. If not, stop and run `/mint-test-step`.
2. Use skill **mint-deployer**: branch, commit (conventional message `step-N: ...`), push, open PR.
3. Watch the pipeline run. On failure, read the failing task log and fix the cause, never loosen the test or the pipeline to get green.
4. After merge to `main`, confirm the staging deployment and run `.agent/skills/mint-deployer/scripts/smoke_test.sh`.
5. Ask the user before promoting to production (the pipeline also enforces an environment approval).
