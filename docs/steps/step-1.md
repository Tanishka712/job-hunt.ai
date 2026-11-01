# Step 1: Storage Ports, Fakes, Cross-User Caches & Azure Adapters

**Risk level:** R0 → R2 (writes only to internal persistence ports)   **Depends on:** S0
**New capability (one LLM + one tool):** Persistence layer behind strict `Protocol` interfaces (`ProfileRepo`, `JobHashRepo`, `GlobalJobCacheRepo`, `CompanyBriefCacheRepo`, `ApplicationRepo`, `ThreadStore`, `AgentSessionStore`, `OutreachLogRepo`, `BlobStore`, `VectorStore`), in-memory fakes with controllable clock/TTL & ETag concurrency, Azure SDK adapter wrappers, and idempotent master data seeding.
**Data touched (read / write):**
- Cosmos containers: `profile` (`/user_id`), `job_hashes` (`/user_id`, 30d TTL), `global_jobs` (`/job_hash`, 30d TTL), `company_briefs` (`/company_key`, 7d TTL), `applications` (`/user_id`), `threads` (`/thread_id`), `agent_sessions` (`/session_id`, ETag optimistic concurrency), `outreach_log` (`/user_id`).
- Blob containers: `resumes-master`, `resumes-tailored`, `screenshots` (with short-lived read-only SAS URLs).
- Vector index: `master-cv-chunks` (filtered strictly by `user_id`).
**Acceptance tests:**
- [x] Contract test suite per port passes against `InMemory*` fakes (and supports real Azure adapters via `@pytest.mark.integration`).
- [x] TTL test verifies `job_hashes` (30d), `global_jobs` (30d), and `company_briefs` (7d) configure `default_ttl` and expire items when the clock advances past TTL.
- [x] `AgentSessionStore` enforces ETag optimistic concurrency (`ConcurrencyError` on stale write) and stores `state`, `turn`, and `version` docs separately.
- [x] `BlobStore` round-trips bytes and generates read-only SAS URLs (`sp=r`) that expire after the requested duration.
- [x] `VectorStore` returns expected `CVChunk`s for a known query and strictly isolates chunks by `user_id`.
- [x] Safety test verifies `ProfileRepo` rejects raw password/secret fields and `ports/storage.py` has zero Azure SDK imports.
- [x] Master data seed utility (`seed_master_data`) is idempotent across repeated runs.
**Out of scope:** Any LLM calls, external web scraping, or agent graphs.
**Rollback:** Additive storage layer only; revert branch or switch composition root back to no-op.
