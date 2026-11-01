# Step S4: Resume Customizer Agent (Own State, Conversational Memory, Verifier & PDF Renderer)

## Goal
Build the `S4` Resume Customizer Agent (`R2`) with its own isolated conversational session (`resume:{user_id}:{job_id}`), semantic CV retrieval tool (`search_master_cv`), reasoning LLM (`ANALYTICAL_REASONER`: `openai/gpt-oss-120b` $\to$ fallback `qwen/qwen3.8-27b`), truthfulness & pinned-constraint verifier, Markdown + single-page PDF renderer stored in `BlobStore` (`resumes-tailored`), iterative refinement graph (`edit`, `question`, `revert`, `compare`), FastAPI endpoints, and CLI subcommands.

## Risk Level
- **`R2` (`Risk.R2_WRITE_INTERNAL`)**: Retrieves CV chunks from `VectorStore` (`R1`) and writes tailored resume versions (`.pdf` and `.md`) to `BlobStore` (`resumes-tailored`) and session state/turns/versions to `AgentSessionStore` (`agent_sessions`). Zero external side effects.

## One LLM + Tools Added
1. **Retrieval Tool**: `search_master_cv` (`@tool("search_master_cv", risk=Risk.R1_READ_EXTERNAL)`) querying `VectorStore` strictly scoped to `user_id`.
2. **Render Tool**: `render_and_store_resume` (`@tool("render_resume_pdf", risk=Risk.R2_WRITE_INTERNAL)`) rendering Markdown + valid single-page PDF bytes and uploading to `BlobStore` container `resumes-tailored` under `{user_id}/{job_id}/v{version}.pdf` and `.md`.
3. **LLM Nodes**:
   - `ANALYTICAL_REASONER` (`openai/gpt-oss-120b`, fallback `qwen/qwen3.8-27b`) for drafting and revising `ResumeDraftContent`.
   - `LIGHTWEIGHT_PARSER` (`openai/gpt-oss-20b`, fallback `allam-2-7b`) for classifying refinement intent (`edit | question | revert | compare`) and extracting durable `pinned_instructions`.

## Data Touched
- `VectorStore` (`master-cv-chunks`): read-only semantic chunk retrieval per `user_id`.
- `AgentSessionStore` (`agent_sessions`, `/session_id`): stores `ResumeState`, per-turn `SessionTurnDoc`, and immutable `SessionVersionDoc` with ETag concurrency control.
- `BlobStore` (`resumes-tailored`): stores `{user_id}/{job_id}/v{version}.pdf` and `{user_id}/{job_id}/v{version}.md`.

## Acceptance Tests
1. **Truthfulness & Chunk Citation Verifier**:
   - Every bullet must cite at least one valid `source_chunk_id` from `retrieved_chunks`.
   - Invented claims (unknown chunk IDs, fabricated metrics like `999%`, or ungrounded employer claims) are rejected by `verify_resume_draft`.
   - Failed verifier runs after retry exhaustion create no new version and return the verifier report.
2. **Conversational Memory, Pinned Instructions & Trimming**:
   - Durable instructions stated in Turn 1 (e.g., `"Keep to one page and never mention Kubernetes"`) are persisted in `pinned_instructions`, survive rolling turn trimming (>6 turns), and are enforced by the verifier at Turn 3+.
3. **Byte-Exact Version Revert & Deterministic Compare**:
   - Reverting to version `v1` restores the exact bytes of `v1` from `BlobStore` with 0 LLM calls.
   - Comparing two versions returns a unified diff with 0 LLM calls.
4. **Isolation & Safety (`tests/safety/test_agent_isolation.py`)**:
   - Editing `job-A` never modifies `job-B`.
   - `src/app/agents/resume` never imports from `src/app/agents/email`.
5. **PDF Rendering**:
   - Rendered PDF bytes are valid (`%PDF-1.4`) and respect the single-page constraint when pinned.

## Out of Scope
- Email outreach drafting (`S7`), contact discovery (`S5`), company web search (`S6`), or external submission (`S10`–`S11`).
