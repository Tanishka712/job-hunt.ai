# Resume and Email Agents: separate state, conversational memory, iterative refinement

Two agents, two independent sessions. The user talks to each one separately in the UI ("make the second bullet more quantitative" goes to the resume agent; "warmer tone" goes to the email agent). They must not share a message list, a state object, or a version history.

## Session identity
- Resume: `session_id = "resume:{job_id}"`
- Email: `session_id = "email:{job_id}:{contact_id}"` (one session per contact, because tone differs per recipient)
Both are stored in the `agent_sessions` container, partition key `/session_id`.

## State schemas (separate Pydantic models, separate modules)
```python
class ResumeState(BaseModel):
    session_id: str
    job_id: str
    jd_requirements: list[str]
    retrieved_chunks: list[Chunk]          # id + text, evidence for every bullet
    pinned_instructions: list[str]         # durable user preferences ("never mention X", "keep to one page")
    current_version: int
    summary_of_older_turns: str = ""       # rolling summary, see trimming
    # messages live as per-turn docs, not inside this object

class EmailState(BaseModel):
    session_id: str
    job_id: str
    contact_id: str
    handoff: EmailHandoff                  # JobContext + Contact + resume summary + CompanyBrief (read-only)
    pinned_instructions: list[str]         # tone, length, things to avoid
    current_version: int
    summary_of_older_turns: str = ""
```
Why separate: different evidence (CV chunks vs. recipient + company), different verifiers, different lifetimes. An import-boundary test (`tests/safety/test_agent_isolation.py`) asserts neither package imports the other.

## Stored documents (type field distinguishes them)
- `state`: the object above.
- `turn`: `{role, content, ts, version_after, intent}` one per user/agent message.
- `version`: `{n, content_ref, created_by_turn, verifier_report, parent_version}`. Content is in Blob for resumes; email bodies are small and stored inline.

## Refinement graph (same shape for both, different nodes)
```
load_session
  → classify_intent  (edit | question | revert | compare | approve)
  → edit:    build_prompt(state, pinned, last N turns, summary) → LLM → verify → save version → reply
  → question: answer from state; no new version
  → revert:  set current_version to chosen; no LLM call
  → compare: diff two versions; no LLM call
```
- **classify_intent** is a cheap-model call with a Pydantic enum output. Revert and compare involve no generation at all, which keeps them deterministic and free.
- **Pinned instructions:** when the user states a durable preference, a cheap extractor adds it to `pinned_instructions` so it survives trimming. Test: a preference from turn 1 is still honored at turn 15.
- **Trimming:** keep the last 6 turns verbatim + `summary_of_older_turns`; regenerate the summary every 6 turns. Never drop `pinned_instructions`.
- **Versioning:** every successful edit creates a new immutable version. The user can revert to any version. Failed verifier runs create no version and return the verifier's reason to the user.
- **Concurrency:** use the Cosmos ETag on the `state` doc; a stale write fails and the request is retried once.

## Verifiers
- Resume: every bullet maps to at least one `retrieved_chunks` id; no new employers, titles, dates, degrees, metrics or skills absent from the chunks; one-page limit if pinned; PII-free of secrets.
- Email: < 150 words, exactly one clear call to action, no PII beyond the profile fields allowed for outreach, no claims absent from the resume summary or company brief, subject present.
If verification fails twice, return the best draft *plus* the failing checks so the human can decide; never silently ship an unverified draft.

## API (S4 and S7)
```
POST /jobs/{job_id}/resume/refine        {message}   → SSE: tokens, then {version, verifier_report}
GET  /jobs/{job_id}/resume/versions
POST /jobs/{job_id}/resume/revert        {version}
POST /jobs/{job_id}/email/{contact_id}/refine
GET  /jobs/{job_id}/email/{contact_id}/versions
POST /jobs/{job_id}/email/{contact_id}/revert
```
Approval (S8) names exact version numbers, so what the user approved is what gets used.
