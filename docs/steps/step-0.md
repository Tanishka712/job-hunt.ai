# Step 0: Skeleton + CI/CD

**Risk level:** R0 (pure logic, no external I/O)   **Depends on:** None
**New capability (one LLM + one tool):** None (delivery skeleton only: FastAPI `/health` and `/version` endpoints, `Settings`, Dockerfile, GitHub Actions CI/CD workflow, static & test gate configuration).
**Data touched (read / write):** None (reads `GIT_SHA` and `ENVIRONMENT` from environment variables via `pydantic-settings`).
**Acceptance tests:**
- [x] `GET /health` returns HTTP 200 with `{"status": "ok"}`.
- [x] `GET /version` returns HTTP 200 with the configured `git_sha` and `environment`.
- [x] `ruff check .`, `ruff format --check .`, and `mypy src` pass with zero errors.
- [x] `pytest` universal gate runs unit tests with coverage and passes.
- [x] `Dockerfile` and `.github/workflows/ci-cd.yml` are valid and pass `GIT_SHA` build arg.
**Out of scope:** Any LLM client, any storage adapter (Cosmos, Blob, AI Search), any agent or scraping tool.
**Rollback:** Revert commit or shift 100% traffic to the previous Azure Container App revision (`az containerapp ingress traffic set`).
