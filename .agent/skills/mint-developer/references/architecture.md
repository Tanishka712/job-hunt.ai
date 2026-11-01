# Architecture Reference

## Components
- **UI:** Azure Static Web Apps (Next.js). HITL dashboard.
- **API + orchestration:** Azure Container Apps running FastAPI + LangGraph. HTTPS REST + SSE.
- **Worker:** Azure Container Apps **Job** running Playwright, triggered by the approval queue.
- **Models (Provider: Groq):**
  - **Fast / Ingestion Tier (`llama-3.1-8b-instant`):** Scraping/parsing (`JobSpec`), Networker search queries, Company Research summarization, deterministic verifier checks. (~800–1,200 t/s, ultra-low cost).
  - **Reasoning Tier (`llama-3.3-70b-versatile`):** Resume customization (S4) against master CV chunks, personalized outreach drafting (S7) under 150 words.
  - **Vision Tier (`llama-3.2-11b-vision-preview`):** Playwright dry-run screenshot inspection and form verification (S10/S11).
  - Configured via `GROQ_API_KEY` with fallback & token budgeting in S2.
- **CI/CD:** GitHub push → **GitHub Actions** (2,000 free min/month, Azure Service Principal/OIDC) → lint/test → image to ACR → deploy to Azure Container Apps. **Azure DevOps** integrated via webhooks/Azure Boards for backlog tracking, deployment events, and audit logging.

## Memory mapping
| Memory | Where | What |
|---|---|---|
| Working | LangGraph state / FastAPI context | job URL, raw HTML, intermediate JSON, current draft, selected contact. Checkpointed to Cosmos only at the HITL gate. |
| Episodic | Cosmos DB | 30-day job hashes (TTL), application log and statuses, HITL edit history, outreach log, agent conversation sessions |
| Semantic | Azure AI Search (FAISS locally) | chunks of master CV, projects, skills matrix, outreach templates, scraper selectors/taxonomies |
| Documents | Blob Storage | master resume, tailored resumes (PDF + MD/LaTeX) per job and version, screenshots |

## Cosmos containers
| Container | Partition key | Notes |
|---|---|---|
| `profile` | `/user_id` | name, email, phone, links, address. **No passwords.** |
| `job_hashes` | `/user_id` | id = normalized hash; container `defaultTtl` = 2592000 s (30 d). TTL only works if `defaultTtl` is set on the container. |
| `applications` | `/user_id` | status: `AWAITING_APPROVAL`, `APPROVED`, `APPLIED`, `FAILED`; HITL edit log |
| `threads` | `/thread_id` | LangGraph checkpoints for the HITL pause |
| `agent_sessions` | `/session_id` | resume and email conversational memory; docs of type `state`, `turn`, `version` (one doc per turn so no single doc nears the 2 MB limit) |
| `outreach_log` | `/user_id` | contacts already approached |

Blob containers: `resumes-master`, `resumes-tailored` (`{job_id}/v{n}.pdf|.md|.tex`), `screenshots`.
AI Search index `master-cv-chunks`: `id, content, content_vector, section, source, tags, date`.

## Deliberate deviations from the original design doc (flag to user on S1)
1. **Credentials:** the doc places "user credentials" in Cosmos. Store them in **Azure Key Vault** and let only the worker's managed identity read them; Cosmos keeps non-secret autofill values.
2. **Hash:** `company + title` collides for the same title in different cities and misses re-posts with cosmetic changes. Normalize (lowercase, strip punctuation/seniority noise) and consider adding location. Keep it as a pure, tested function.
3. **GitHub → Azure Pipelines:** use the *Azure Pipelines* GitHub App/service connection rather than hand-made webhooks; it registers the triggers and posts check status on PRs.
4. **Automation risk:** LinkedIn and many ATS sites forbid scraping/auto-apply and use bot detection. Treat S5 and S11 as best-effort with a manual fallback, and never circumvent CAPTCHAs.

## Handoff types (Pydantic)
`JobSpec`, `JobContext`, `Contact`, `ContactList`, `CompanyBrief`, `ResumeArtifact {version, blob_url, summary, source_chunk_ids}`, `EmailDraft {version, subject, body, contact_id}`, `ApprovalPayload {job_id, contact_id, resume_version, email_version, nonce, hmac}`.
