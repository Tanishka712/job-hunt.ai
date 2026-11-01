# Azure + GitHub + Azure Pipelines Setup

Run commands with the user's confirmation; they create billable resources. Names below are placeholders. Check the current Azure CLI docs if a command errors, as flags change between versions.

## Contents
1. One-time setup · 2. Add data services per step · 3. Pipeline connection · 4. Variable group · 5. Environments and approvals · 6. Rollback · 7. Playwright job (S10)

## 1. One-time setup (S0)
```bash
az login
az group create -n rg-mint -l centralindia          # pick the region nearest the user
az acr create -g rg-mint -n <acrname> --sku Basic
az monitor log-analytics workspace create -g rg-mint -n log-mint
az containerapp env create -g rg-mint -n cae-mint -l centralindia
az containerapp create -g rg-mint -n mint-api-staging --environment cae-mint \
  --image mcr.microsoft.com/k8se/quickstart:latest --target-port 8000 --ingress external \
  --min-replicas 0 --max-replicas 2 --system-assigned
az keyvault create -g rg-mint -n kv-mint-<unique>
az consumption budget create ...   # or set a budget alert in the portal at 50% and 80%
```
Grant the Container App's managed identity `AcrPull` on the registry and `Key Vault Secrets User` on the vault.

## 2. Add data services only when their step arrives (S1)
```bash
az cosmosdb create -g rg-mint -n cosmos-mint --capabilities EnableServerless
az cosmosdb sql database create -a cosmos-mint -g rg-mint -n mint
az cosmosdb sql container create -a cosmos-mint -g rg-mint -d mint -n job_hashes \
  --partition-key-path /user_id --ttl 2592000
# repeat for profile, applications, threads (/thread_id), agent_sessions (/session_id), outreach_log
az storage account create -g rg-mint -n stmint<unique> --sku Standard_LRS --allow-blob-public-access false
az search service create -g rg-mint -n search-mint --sku free
```
Use **managed identity / Entra ID auth** from the app to Cosmos, Blob and Search (RBAC roles: Cosmos DB Built-in Data Contributor, Storage Blob Data Contributor, Search Index Data Contributor) instead of connection strings. Keep a separate **dev** set of resources (or a `-dev` database/containers) for integration tests so tests never touch real data.

## 3. Connect GitHub Actions to Azure + Webhook to Azure DevOps
1. **Create Azure Service Principal for GitHub Actions:**
   ```bash
   az ad sp create-for-rbac --name "sp-mint-github" --role contributor \
     --scopes /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-mint \
     --sdk-auth
   ```
   Save the output JSON to GitHub Secret `AZURE_CREDENTIALS`.
2. **GitHub Repository Secrets:**
   In your GitHub Repo → Settings → Secrets and variables → Actions:
   - `AZURE_CREDENTIALS`: Service Principal JSON output.
   - `ACR_NAME`: Azure Container Registry name.
   - `AZURE_RESOURCE_GROUP`: `rg-mint`.
   - `AZURE_CONTAINER_APP_NAME`: `mint-api-staging`.
   - `STAGING_URL`: public URL of the Container App (e.g. `https://mint-api-staging.<region>.azurecontainerapps.io`).
   - `AZURE_DEVOPS_WEBHOOK_URL`: (Optional) Webhook or API endpoint to notify Azure DevOps.
3. **Connect to Azure DevOps via Webhook / Azure Boards:**
   - **For Backlog & Board sync (Simplest & Best):** Install the official free **Azure Boards app from GitHub Marketplace**. Any commit with `AB#<ID>` automatically links and updates user stories on your Azure DevOps Kanban board.
   - **For Deployment Notifications via Webhook:** In Azure DevOps → Project Settings → Service Connections → New **Incoming Webhook** connection, or use a Service Hook to receive payloads from GitHub Actions when a build/deployment completes.

## 4. Variable group `mint-shared`
Library → Variable groups. Non-secret: `acrName`, `resourceGroup`, `stagingAppName`, `prodAppName`, `stagingUrl`, `prodUrl`, `azureServiceConnection`. Secret values: link to Key Vault (grant the service connection `Get/List` on secrets). Dev data endpoints for integration tests: `devCosmosEndpoint`, `devBlobAccountUrl`, `devSearchEndpoint`.

## 5. Environments and approvals
Pipelines → Environments: create `mint-staging` (no approval) and `mint-prod` (Approvals and checks → add the user as approver). The `DeployProd` stage then pauses until approved.

## 6. Rollback
```bash
az containerapp revision list -g rg-mint -n mint-api-prod -o table
az containerapp ingress traffic set -g rg-mint -n mint-api-prod --revision-weight <previous-revision>=100
```
(Requires revision mode `multiple`: `az containerapp revision set-mode --mode multiple`.) Verify with the smoke test, then open a fix-forward PR.

## 7. Playwright worker (S10)
A **Container Apps Job** triggered by the approval queue (Storage Queue or Service Bus), image based on `mcr.microsoft.com/playwright/python`, its own managed identity with: read on Key Vault secrets for account credentials, read on `resumes-tailored`, write on `screenshots`, read profile in Cosmos, write application status. Keep submit disabled via an env flag (`ALLOW_SUBMIT=false`) until S11. Set `replica-timeout` and `replica-retry-limit 0` so a failed run does not resubmit.
