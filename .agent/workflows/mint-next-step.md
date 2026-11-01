---
description: Run the full MINT loop for the next unfinished step: plan, implement, test, push, deploy, report.
---

1. Read `docs/PROGRESS.md` (create from `.agent/skills/mint-developer/assets/PROGRESS.template.md` if missing). Identify the first step not marked DONE.
2. Use skill **mint-developer**: write the step brief (scope, risk level, acceptance tests) into `docs/steps/step-N.md`. Show it to the user in two or three lines and continue unless they object.
3. Use skill **mint-developer**: write failing tests first, then the minimal implementation.
4. Use skill **mint-tester**: run the step gate. If anything fails, go back to step 3. Do not push red code.
5. Use skill **mint-deployer**: create a branch `step-N-<slug>`, push, open a PR, watch Azure Pipelines, deploy to staging, run the smoke test.
6. Update `docs/PROGRESS.md` and `docs/test-reports/step-N.md`.
7. Report: what was built, test evidence, deployed URL, risks, and the proposed next step. **Stop and wait for the user.**
