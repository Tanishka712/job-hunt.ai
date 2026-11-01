"""Deterministic CV match scorer (0-100) comparing JobSpec against user CV chunks and profile."""

import re

from app.agents.job_finder.schemas import JobSpec
from app.ports.storage import CVChunk, UserProfile


def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9+#.]+", text.lower()) if len(tok) > 1}


def compute_match_score(
    job_spec: JobSpec,
    cv_chunks: list[CVChunk],
    profile: UserProfile | None = None,
) -> float:
    """Compute a deterministic 0-100 CV match score for a parsed JobSpec.

    Scoring breakdown:
    - 65 pts max: required_skills overlap against CV chunk content and tags
    - 15 pts max: nice_to_have_skills overlap (full 15 pts if none listed and required >= 60%)
    - 20 pts max: role title & responsibilities keyword alignment with CV + profile.target_roles
    """
    if not cv_chunks and profile is None:
        return 50.0

    cv_corpus = " ".join(
        f"{chunk.section} {chunk.content} {' '.join(chunk.tags)}" for chunk in cv_chunks
    ).lower()
    if profile is not None:
        cv_corpus += " " + " ".join(profile.target_roles).lower()
    cv_tokens = _tokenize(cv_corpus)

    # 1. Required skills score (0 - 65)
    req_skills = [s.strip().lower() for s in job_spec.required_skills if s.strip()]
    if req_skills:
        matched_req = 0
        for skill in req_skills:
            skill_tokens = _tokenize(skill)
            if skill in cv_corpus or (skill_tokens and skill_tokens.issubset(cv_tokens)):
                matched_req += 1
        req_ratio = matched_req / len(req_skills)
        req_score = req_ratio * 65.0
    else:
        req_ratio = 0.5
        req_score = 32.5

    # 2. Nice-to-have skills score (0 - 15)
    nice_skills = [s.strip().lower() for s in job_spec.nice_to_have_skills if s.strip()]
    if nice_skills:
        matched_nice = sum(
            1
            for skill in nice_skills
            if skill in cv_corpus or (_tokenize(skill) and _tokenize(skill).issubset(cv_tokens))
        )
        nice_score = (matched_nice / len(nice_skills)) * 15.0
    else:
        nice_score = 15.0 if req_ratio >= 0.5 else req_ratio * 15.0

    # 3. Title & responsibilities alignment (0 - 20)
    role_text = f"{job_spec.title} {' '.join(job_spec.responsibilities)}"
    role_tokens = _tokenize(role_text)
    if role_tokens:
        overlap = len(role_tokens & cv_tokens) / max(1, min(len(role_tokens), 12))
        role_score = min(20.0, overlap * 20.0)
    else:
        role_score = 10.0

    total = round(min(100.0, max(0.0, req_score + nice_score + role_score)), 1)
    return total
