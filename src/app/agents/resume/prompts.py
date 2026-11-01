"""Versioned prompt templates for S4 Resume Customizer Agent."""

from app.ports.storage import CVChunk, SessionTurnDoc

RESUME_DRAFT_V1 = """Create a tailored ResumeDraftContent JSON instance for the target job below.

STRICT TRUTHFULNESS & CITATION RULES:
1. Every bullet in `bullets` MUST cite one or more valid chunk IDs from
   `RETRIEVED MASTER CV CHUNKS` in `source_chunk_ids`.
2. Do NOT invent employers, titles, dates, degrees, metrics (like percentages), or technologies
   absent from the retrieved CV chunks.
3. Honor all `PINNED USER INSTRUCTIONS` unconditionally.

TARGET JOB REQUIREMENTS:
{jd_requirements}

PINNED USER INSTRUCTIONS:
{pinned_instructions}

RETRIEVED MASTER CV CHUNKS:
{chunks_block}
"""

RESUME_REFINE_V1 = """Revise the current ResumeDraftContent JSON instance per the user's feedback.

STRICT TRUTHFULNESS & CITATION RULES:
1. Every bullet in `bullets` MUST cite one or more valid chunk IDs from
   `RETRIEVED MASTER CV CHUNKS` in `source_chunk_ids`.
2. Do NOT invent any claim, metric, or skill absent from the retrieved CV chunks.
3. You MUST obey all `PINNED USER INSTRUCTIONS` (even if stated in earlier turns).

TARGET JOB REQUIREMENTS:
{jd_requirements}

PINNED USER INSTRUCTIONS:
{pinned_instructions}

SUMMARY OF OLDER CONVERSATION TURNS:
{summary_of_older_turns}

RECENT CONVERSATION TURNS:
{recent_turns}

CURRENT DRAFT JSON:
{current_draft_json}

RETRIEVED MASTER CV CHUNKS:
{chunks_block}

LATEST USER REQUEST:
{user_message}
"""

RESUME_INTENT_V1 = """Classify the user's message for the Resume Customizer session.

Rules:
- Set `intent` to one of: `"edit"`, `"question"`, `"revert"`, `"compare"`, `"approve"`.
- If the user states a durable rule/preference (e.g., "never mention X", "always keep to one page"),
  copy that rule into `pinned_instruction_to_add`.
- If `intent` is `"revert"`, extract the integer version number into `target_version`.
- If `intent` is `"compare"`, extract `compare_from_version` and `target_version`.

User Message: {message}
"""


def format_chunks_for_prompt(chunks: list[CVChunk]) -> str:
    """Format retrieved CV chunks with their IDs for the LLM prompt."""
    lines = []
    for c in chunks:
        tags = ", ".join(c.tags)
        lines.append(f"- ID: {c.id} | Section: {c.section} | Tags: [{tags}] | Text: {c.content}")
    return "\n".join(lines) if lines else "(No CV chunks retrieved)"


def format_turns_for_prompt(turns: list[SessionTurnDoc]) -> str:
    """Format recent conversation turns for the refinement prompt."""
    if not turns:
        return "(No prior turns)"
    return "\n".join(f"[{t.role} (turn {t.turn_index})]: {t.content}" for t in turns)
