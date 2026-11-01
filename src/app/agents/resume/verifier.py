"""Deterministic truthfulness, citation, one-page, and pinned-constraint verifier for S4."""

import re

from app.agents.resume.schemas import ResumeDraftContent, ResumeVerifierReport
from app.guardrails.pii_shield import contains_secret
from app.ports.storage import CVChunk

_NUMBER_CLAIM_RE = re.compile(r"\b\d+(?:\.\d+)?(?:%|x|k|m|b|\+)\b", re.IGNORECASE)
_NEVER_MENTION_RE = re.compile(
    r"(?:never\s+mention|do\s+not\s+mention|don't\s+mention|exclude|avoid\s+mentioning)\s+([a-z0-9+#.\-_]+)",
    re.IGNORECASE,
)


def _extract_forbidden_terms(pinned_instructions: list[str]) -> list[str]:
    forbidden: list[str] = []
    for instruction in pinned_instructions:
        for match in _NEVER_MENTION_RE.finditer(instruction):
            term = match.group(1).strip(" .,;:\"'").lower()
            if term and term not in forbidden:
                forbidden.append(term)
    return forbidden


def _is_one_page_pinned(pinned_instructions: list[str]) -> bool:
    joined = " ".join(pinned_instructions).lower()
    return "one page" in joined or "1 page" in joined or "single page" in joined


def verify_resume_draft(
    draft: ResumeDraftContent,
    *,
    retrieved_chunks: list[CVChunk],
    jd_requirements: list[str],
    pinned_instructions: list[str],
) -> ResumeVerifierReport:
    """Verify every bullet traces to `retrieved_chunks` with zero invented claims or violations."""
    violations: list[str] = []
    chunk_map: dict[str, CVChunk] = {c.id: c for c in retrieved_chunks}

    all_chunk_text = " ".join(
        f"{c.content} {' '.join(c.tags)} {c.section} {c.date}" for c in retrieved_chunks
    ).lower()
    allowed_numbers = set(_NUMBER_CLAIM_RE.findall(all_chunk_text))

    valid_chunk_citations = True
    no_invented_claims = True

    # 1. Verify chunk citations and factual grounding per bullet
    for idx, bullet in enumerate(draft.bullets, start=1):
        if not bullet.source_chunk_ids:
            valid_chunk_citations = False
            violations.append(f"Bullet {idx} has no source_chunk_ids.")
            continue

        cited_chunks: list[CVChunk] = []
        for cid in bullet.source_chunk_ids:
            if cid not in chunk_map:
                valid_chunk_citations = False
                no_invented_claims = False
                violations.append(
                    f"Bullet {idx} cites unknown chunk ID '{cid}' not in retrieved_chunks."
                )
            else:
                cited_chunks.append(chunk_map[cid])

        # Check quantitative/metric claims (e.g. 999%, 10x, $5M) are present in the CV chunks
        bullet_numbers = _NUMBER_CLAIM_RE.findall(bullet.text.lower())
        for num in bullet_numbers:
            if num not in allowed_numbers:
                no_invented_claims = False
                violations.append(
                    f"Bullet {idx} contains invented metric '{num}' absent from master CV chunks."
                )

        # Check that at least 2 meaningful words (>=4 chars) in the bullet overlap with cited chunks
        if cited_chunks:
            cited_text = " ".join(f"{c.content} {' '.join(c.tags)}" for c in cited_chunks).lower()
            cited_words = set(re.findall(r"[a-z0-9+#.]{3,}", cited_text))
            bullet_words = set(re.findall(r"[a-z0-9+#.]{3,}", bullet.text.lower()))
            if len(bullet_words & cited_words) < 2:
                no_invented_claims = False
                violations.append(
                    f"Bullet {idx} has insufficient lexical overlap with "
                    f"cited chunks {bullet.source_chunk_ids}."
                )

    # 2. Check pinned negative constraints ("never mention X")
    full_draft_text = (
        f"{draft.professional_summary} "
        + " ".join(b.text for b in draft.bullets)
        + " "
        + " ".join(draft.highlighted_skills)
    )
    full_lower = full_draft_text.lower()
    for term in _extract_forbidden_terms(pinned_instructions):
        if re.search(rf"\b{re.escape(term)}\b", full_lower):
            violations.append(
                f"Draft violates pinned instruction: forbidden term '{term}' is present."
            )

    # 3. Check one-page constraint (<= 8 bullets and <= 400 words)
    word_count = len(full_draft_text.split())
    one_page_ok = True
    if _is_one_page_pinned(pinned_instructions) and (len(draft.bullets) > 8 or word_count > 400):
        one_page_ok = False
        violations.append(
            f"Draft exceeds one-page budget ({len(draft.bullets)} bullets, {word_count} words)."
        )

    # 4. Check PII / secret shield
    pii_free = not contains_secret(full_draft_text)
    if not pii_free:
        violations.append("Draft contains raw PII or secret credentials.")

    passed = (
        valid_chunk_citations
        and no_invented_claims
        and one_page_ok
        and pii_free
        and len(violations) == 0
    )
    return ResumeVerifierReport(
        passed=passed,
        checked_bullets=len(draft.bullets),
        valid_chunk_citations=valid_chunk_citations,
        no_invented_claims=no_invented_claims,
        one_page_ok=one_page_ok,
        pii_free=pii_free,
        violations=violations,
    )
