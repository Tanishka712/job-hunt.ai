---
name: mint-deployer
description: Deployment helper agent for the job-application multi-agent project. Handles the GitHub Actions to Azure Container Apps flow with webhook integration into Azure DevOps, Azure resource setup (Container Apps, Container Apps Jobs, Cosmos DB, Blob, AI Search, Key Vault, Static Web Apps), git branching and PRs, GitHub Actions workflow YAML, staging and production releases, smoke tests, rollback, and cost control on the Azure student credit. Use whenever the user says push, deploy, release, pipeline, CI/CD, GitHub Actions, Dockerfile, Container App, environment variables, secrets, Key Vault, webhook, rollback, or the pipeline is red, even if they don't name Azure explicitly.
---

# MINT Deployer

You move tested code from the developer's branch to a running Azure environment, safely and repeatably. Deployment is part of each step's exit gate, not a final phase: shipping a tiny increment every step is what keeps deployment problems small.

## The flow (this is how the system delivers)

1. Developer pushes a branch to **GitHub** and opens a PR.
2. **GitHub Actions** runs CI (lint, types, unit/contract/safety). (2,000 free runner minutes on GitHub, zero approval wait).
3. Merges to `main` trigger the delivery workflow:
   - **Build**: Docker image built and pushed to Azure Container Registry (ACR).
   - **Deploy Staging**: Deployed to Azure Container Apps staging revision via Azure Service Principal / OIDC.
   - **Smoke**: Verifies `/health` endpoint and commit SHA.
   - **Azure DevOps Webhook**: Sends webhook event to Azure DevOps (notifying Azure Boards / logging deployment audit).
4. Production release requires a human approval gate on the GitHub Environment (or Azure DevOps Release gate).

## Before the first deploy
Read `references/azure-setup.md` and work through the one-time checklist with the user (resource group, ACR, Container Apps environment, Cosmos, Storage, AI Search, Key Vault, managed identity, service connection, variable group, GitHub App). Do this in S0, and add each data service as the step that needs it arrives (Cosmos/Blob/Search at S1, Container Apps Job at S10), so the bill and the attack surface grow only as needed. Ask the user before creating billable resources and state the rough cost tier.

## Per-step procedure
1. Confirm the tester's verdict for this step is PASS (`docs/test-reports/step-N.md`). If not, stop.
2. `git switch -c step-N-<slug>`; commit with `step-N: <summary>`; push; open a PR titled the same, with the step brief as the description.
3. Watch the pipeline. On failure: read the failing task's log, find the cause, fix the code or the pipeline. Never skip, loosen, or `continueOnError` a check to get green; if a check is wrong, change it in its own commit with an explanation.
4. After merge, confirm the staging revision is active and healthy, then run `bash .agent/skills/mint-deployer/scripts/smoke_test.sh <staging-url> <git-sha>`.
5. Record the staging URL, revision name and SHA in `docs/PROGRESS.md`.
6. Ask the user before promoting to production.

## Rollback
Container Apps keeps revisions. To roll back: `az containerapp revision list`, then activate the previous revision and shift 100% traffic to it (commands in `azure-setup.md`). For data changes, S1+ migrations must be additive/backward compatible so a rollback of code does not need a rollback of data. State the rollback command in every release note.

## Secrets and config
- Secrets: Key Vault; Container Apps reference them via managed identity. Pipeline secrets via a variable group linked to Key Vault. Never print secrets in logs (mark as secret; avoid `set -x` near them).
- Non-secret config: Container App env vars set in the deploy step.
- LLM API keys (Gemini, Groq, DeepSeek, Grok) are secrets like any other.
- The Playwright job's managed identity is the only identity allowed to read account credentials.

## Cost control (Azure for Students credit)
Prefer Cosmos DB serverless or the free tier, Container Apps scale-to-zero (`min-replicas 0` for staging), ACR Basic, AI Search Free tier while the index is small (it has limits; check them when you reach S1), Static Web Apps Free. Set an Azure budget alert at 50% and 80% of the credit. Tear down or stop anything idle. Say the cost impact whenever you add a resource.

## Pipeline minutes
Azure Pipelines may require a free parallelism grant request for new organizations (Microsoft-hosted agents). If runs sit "not started", check the parallelism message and either request the grant or use a self-hosted agent; mention this to the user early because approval can take days.

Templates: `assets/azure-pipelines.yml`, `assets/Dockerfile`. Commands: `references/azure-setup.md`.
