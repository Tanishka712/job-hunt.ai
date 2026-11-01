# MINT Antigravity Agents

A developer, an execution tester and a deployment helper for building the job-application multi-agent system step by step with MINT (Minimal Intelligence, Necessary Tools).

## Install
Copy the `.agent/` folder into the **root of your project repo** (the folder Antigravity opens). Commit it so the agents travel with the code.

```
.agent/
  rules/00-mint-principles.md        always-on guardrails (set activation to "Always On")
  skills/mint-developer/             plans + writes one step at a time
  skills/mint-tester/                gates each step, writes test reports
  skills/mint-deployer/              GitHub → Azure Pipelines → Container Apps
  workflows/                         /mint-next-step  /mint-test-step  /mint-deploy-step  /mint-status
```

## Use
1. Open the repo in Antigravity and say: **/mint-next-step** (first run starts at S0, the CI/CD skeleton).
2. The agent writes a step brief, writes tests first, implements, runs the gate, pushes a branch, watches Azure Pipelines, deploys to staging, then stops for your go-ahead.
3. Say **/mint-next-step** again for the next step. **/mint-status** shows progress at any time.

The ordered plan is in `.agent/skills/mint-developer/references/build-plan.md`.
