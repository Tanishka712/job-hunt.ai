"""S4 Resume Customizer graph: initial tailoring, conversational refine, revert, and compare."""

import difflib
import json
import re

from app.agents.job_finder.schemas import JobSpec
from app.agents.resume.prompts import (
    RESUME_DRAFT_V1,
    RESUME_INTENT_V1,
    RESUME_REFINE_V1,
    format_chunks_for_prompt,
    format_turns_for_prompt,
)
from app.agents.resume.renderer import render_and_store_resume
from app.agents.resume.schemas import (
    IntentClassification,
    RefinementIntent,
    ResumeArtifact,
    ResumeDraftContent,
    ResumeRefineResult,
    ResumeVerifierReport,
)
from app.agents.resume.state import ResumeState, build_resume_session_id
from app.agents.resume.tools import search_master_cv
from app.agents.resume.verifier import verify_resume_draft
from app.core.container import StorageContainer
from app.ports.llm import AgentRole, LLMClient
from app.ports.storage import SessionTurnDoc, SessionVersionDoc

MAX_RECENT_TURNS = 6
MAX_VERIFIER_RETRIES = 2


def _extract_heuristic_pinned(message: str) -> str | None:
    """Fallback heuristic extractor for durable user instructions ('never mention X', etc.)."""
    lower = message.lower()
    if any(
        phrase in lower
        for phrase in ("never mention", "do not mention", "don't mention", "one page", "1 page")
    ):
        return message.strip()
    return None


async def _generate_and_verify_draft(
    prompt: str,
    *,
    state: ResumeState,
    llm: LLMClient,
    user_api_key: str | None = None,
) -> tuple[ResumeDraftContent, ResumeVerifierReport]:
    """Call ANALYTICAL_REASONER and run the verifier with up to 2 regeneration retries."""
    active_prompt = prompt
    last_draft: ResumeDraftContent | None = None
    last_report: ResumeVerifierReport | None = None

    for _attempt in range(MAX_VERIFIER_RETRIES + 1):
        draft = await llm.complete_structured(
            active_prompt,
            ResumeDraftContent,
            role=AgentRole.ANALYTICAL_REASONER,
            retries=2,
            user_api_key=user_api_key,
        )
        report = verify_resume_draft(
            draft,
            retrieved_chunks=state.retrieved_chunks,
            jd_requirements=state.jd_requirements,
            pinned_instructions=state.pinned_instructions,
        )
        last_draft = draft
        last_report = report
        if report.passed:
            return draft, report

        violation_text = "; ".join(report.violations)
        active_prompt = (
            f"{prompt}\n\n[VERIFIER REJECTED PREVIOUS DRAFT]\n"
            f"Fix these violations immediately: {violation_text}\n"
            f"Only cite valid chunk IDs: {[c.id for c in state.retrieved_chunks]}"
        )

    assert last_draft is not None and last_report is not None
    return last_draft, last_report


async def _save_verified_version(
    state: ResumeState,
    *,
    expected_etag: str | None,
    draft: ResumeDraftContent,
    report: ResumeVerifierReport,
    created_by_turn: int,
    storage: StorageContainer,
) -> ResumeArtifact:
    """Render PDF + Markdown, store version doc, and advance `current_version` with ETag check."""
    new_version = state.current_version + 1
    profile = await storage.profile_repo.get(state.user_id)
    candidate_name = profile.full_name if profile else "MINT Candidate"

    pdf_url, md_url, _, _ = await render_and_store_resume(
        state.user_id,
        state.job_id,
        new_version,
        draft,
        blob_store=storage.blob_store,
        candidate_name=candidate_name,
    )

    parent_ver = state.current_version if state.current_version > 0 else None
    source_ids = sorted({cid for b in draft.bullets for cid in b.source_chunk_ids})
    artifact = ResumeArtifact(
        version=new_version,
        job_id=state.job_id,
        user_id=state.user_id,
        blob_url=pdf_url,
        markdown_blob_url=md_url,
        summary=draft.professional_summary,
        source_chunk_ids=source_ids,
        draft=draft,
        verifier_report=report,
    )

    await storage.agent_session_store.save_version(
        SessionVersionDoc(
            session_id=state.session_id,
            version=new_version,
            content_ref=json.dumps(artifact.model_dump(mode="json")),
            created_by_turn=created_by_turn,
            verifier_report=report.model_dump(mode="json"),
            parent_version=parent_ver,
        )
    )

    state.current_version = new_version
    await storage.agent_session_store.put_state(
        state.session_id,
        state.model_dump(mode="json"),
        expected_etag=expected_etag,
    )
    return artifact


async def create_initial_resume(
    *,
    user_id: str,
    job_id: str,
    job_spec: JobSpec,
    llm: LLMClient,
    storage: StorageContainer,
    pinned_instructions: list[str] | None = None,
    user_api_key: str | None = None,
) -> ResumeArtifact:
    """Create version 1 of a tailored resume for `(user_id, job_id)` from `JobSpec`."""
    session_id = build_resume_session_id(user_id, job_id)
    skills_str = " ".join(job_spec.required_skills)
    resp_str = " ".join(job_spec.responsibilities)
    query = f"{job_spec.title} {skills_str} {resp_str}"
    chunks = await search_master_cv(
        user_id,
        query,
        vector_store=storage.vector_store,
        top_k=5,
    )
    jd_reqs = [job_spec.title, *job_spec.required_skills, *job_spec.responsibilities]

    state = ResumeState(
        session_id=session_id,
        user_id=user_id,
        job_id=job_id,
        jd_requirements=jd_reqs,
        retrieved_chunks=chunks,
        pinned_instructions=list(pinned_instructions or []),
        current_version=0,
    )
    etag = await storage.agent_session_store.put_state(session_id, state.model_dump(mode="json"))

    prompt = RESUME_DRAFT_V1.format(
        jd_requirements="\n".join(f"- {r}" for r in jd_reqs),
        pinned_instructions="\n".join(f"- {p}" for p in state.pinned_instructions) or "(None)",
        chunks_block=format_chunks_for_prompt(chunks),
    )

    draft, report = await _generate_and_verify_draft(
        prompt,
        state=state,
        llm=llm,
        user_api_key=user_api_key,
    )
    return await _save_verified_version(
        state,
        expected_etag=etag,
        draft=draft,
        report=report,
        created_by_turn=0,
        storage=storage,
    )


async def _load_artifact_version(
    session_id: str,
    version: int,
    storage: StorageContainer,
) -> ResumeArtifact:
    versions = await storage.agent_session_store.list_versions(session_id)
    for vdoc in versions:
        if vdoc.version == version:
            return ResumeArtifact.model_validate_json(vdoc.content_ref)
    raise ValueError(f"Resume version {version} not found in session '{session_id}'")


async def revert_resume_version(
    *,
    user_id: str,
    job_id: str,
    target_version: int,
    storage: StorageContainer,
) -> ResumeRefineResult:
    """Revert `current_version` to `target_version` with 0 LLM calls and byte-exact blobs."""
    session_id = build_resume_session_id(user_id, job_id)
    state_dict, etag = await storage.agent_session_store.get_state_with_etag(session_id)
    if state_dict is None:
        raise ValueError(f"Resume session '{session_id}' does not exist.")
    state = ResumeState.model_validate(state_dict)
    artifact = await _load_artifact_version(session_id, target_version, storage)

    state.current_version = target_version
    await storage.agent_session_store.put_state(
        session_id,
        state.model_dump(mode="json"),
        expected_etag=etag,
    )
    return ResumeRefineResult(
        session_id=session_id,
        intent=RefinementIntent.REVERT,
        reply=f"Reverted resume to version {target_version}.",
        current_version=target_version,
        artifact=artifact,
        verifier_report=artifact.verifier_report,
    )


async def compare_resume_versions(
    *,
    user_id: str,
    job_id: str,
    from_version: int,
    to_version: int,
    storage: StorageContainer,
) -> str:
    """Compute a unified diff between two saved Markdown resume versions (0 LLM calls)."""
    md_from = (
        await storage.blob_store.download_bytes(
            "resumes-tailored", f"{user_id}/{job_id}/v{from_version}.md"
        )
    ).decode("utf-8")
    md_to = (
        await storage.blob_store.download_bytes(
            "resumes-tailored", f"{user_id}/{job_id}/v{to_version}.md"
        )
    ).decode("utf-8")
    diff_lines = list(
        difflib.unified_diff(
            md_from.splitlines(),
            md_to.splitlines(),
            fromfile=f"v{from_version}.md",
            tofile=f"v{to_version}.md",
            lineterm="",
        )
    )
    return "\n".join(diff_lines) if diff_lines else "(No differences)"


async def list_resume_versions(
    *,
    user_id: str,
    job_id: str,
    storage: StorageContainer,
) -> list[ResumeArtifact]:
    """List all immutable `ResumeArtifact` versions saved for `(user_id, job_id)`."""
    session_id = build_resume_session_id(user_id, job_id)
    docs = await storage.agent_session_store.list_versions(session_id)
    return [ResumeArtifact.model_validate_json(d.content_ref) for d in docs]


async def refine_resume(
    *,
    user_id: str,
    job_id: str,
    message: str,
    llm: LLMClient,
    storage: StorageContainer,
    user_api_key: str | None = None,
) -> ResumeRefineResult:
    """Execute one conversational refinement turn (`edit | question | revert | compare`)."""
    session_id = build_resume_session_id(user_id, job_id)
    state_dict, etag = await storage.agent_session_store.get_state_with_etag(session_id)
    if state_dict is None:
        raise ValueError(f"Resume session '{session_id}' does not exist.")
    state = ResumeState.model_validate(state_dict)

    turns = await storage.agent_session_store.list_turns(session_id)
    next_turn_idx = len(turns) + 1

    # 1. Classify intent via LIGHTWEIGHT_PARSER
    intent_prompt = RESUME_INTENT_V1.format(message=message)
    classified = await llm.complete_structured(
        intent_prompt,
        IntentClassification,
        role=AgentRole.LIGHTWEIGHT_PARSER,
        retries=2,
        user_api_key=user_api_key,
    )

    # Extract any durable pinned instruction
    pinned_candidate = classified.pinned_instruction_to_add or _extract_heuristic_pinned(message)
    if pinned_candidate and pinned_candidate not in state.pinned_instructions:
        state.pinned_instructions.append(pinned_candidate)

    # Trim older turns if history exceeds MAX_RECENT_TURNS (never dropping pinned_instructions)
    if len(turns) >= MAX_RECENT_TURNS:
        older = turns[:-MAX_RECENT_TURNS]
        older_digest = " | ".join(f"{t.role}: {t.content[:80]}" for t in older[-4:])
        state.summary_of_older_turns = f"{state.summary_of_older_turns} ; {older_digest}".strip(
            " ;"
        )
    recent_turns = turns[-MAX_RECENT_TURNS:]

    await storage.agent_session_store.append_turn(
        SessionTurnDoc(
            session_id=session_id,
            turn_index=next_turn_idx,
            role="user",
            content=message,
            intent=classified.intent.value,
            version_after=None,
        )
    )

    # Handle REVERT without further LLM calls
    if classified.intent == RefinementIntent.REVERT:
        target_v = classified.target_version
        if target_v is None:
            match = re.search(r"\b(\d+)\b", message)
            target_v = int(match.group(1)) if match else max(1, state.current_version - 1)
        return await revert_resume_version(
            user_id=user_id,
            job_id=job_id,
            target_version=target_v,
            storage=storage,
        )

    # Handle COMPARE without further LLM calls
    if classified.intent == RefinementIntent.COMPARE:
        to_v = classified.target_version or state.current_version
        from_v = classified.compare_from_version or max(1, to_v - 1)
        diff_text = await compare_resume_versions(
            user_id=user_id,
            job_id=job_id,
            from_version=from_v,
            to_version=to_v,
            storage=storage,
        )
        return ResumeRefineResult(
            session_id=session_id,
            intent=RefinementIntent.COMPARE,
            reply=f"Comparison between v{from_v} and v{to_v}:",
            current_version=state.current_version,
            diff_text=diff_text,
        )

    # Handle QUESTION (answer from state, no new version created)
    if classified.intent == RefinementIntent.QUESTION:
        current_art = await _load_artifact_version(session_id, state.current_version, storage)
        q_prompt = (
            f"Current resume draft:\n{current_art.draft.model_dump_json(indent=2)}\n\n"
            f"User question: {message}"
        )
        answer = await llm.complete(
            q_prompt,
            role=AgentRole.LIGHTWEIGHT_PARSER,
            user_api_key=user_api_key,
        )
        await storage.agent_session_store.put_state(
            session_id,
            state.model_dump(mode="json"),
            expected_etag=etag,
        )
        await storage.agent_session_store.append_turn(
            SessionTurnDoc(
                session_id=session_id,
                turn_index=next_turn_idx + 1,
                role="assistant",
                content=answer,
                intent=RefinementIntent.QUESTION.value,
                version_after=state.current_version,
            )
        )
        return ResumeRefineResult(
            session_id=session_id,
            intent=RefinementIntent.QUESTION,
            reply=answer,
            current_version=state.current_version,
            artifact=current_art,
            verifier_report=current_art.verifier_report,
        )

    # Handle EDIT: generate revised draft, run verifier, save new version only if verified
    current_art = await _load_artifact_version(session_id, state.current_version, storage)
    refine_prompt = RESUME_REFINE_V1.format(
        jd_requirements="\n".join(f"- {r}" for r in state.jd_requirements),
        pinned_instructions="\n".join(f"- {p}" for p in state.pinned_instructions) or "(None)",
        summary_of_older_turns=state.summary_of_older_turns or "(None)",
        recent_turns=format_turns_for_prompt(recent_turns),
        current_draft_json=current_art.draft.model_dump_json(indent=2),
        chunks_block=format_chunks_for_prompt(state.retrieved_chunks),
        user_message=message,
    )

    draft, report = await _generate_and_verify_draft(
        refine_prompt,
        state=state,
        llm=llm,
        user_api_key=user_api_key,
    )

    if not report.passed:
        # Failed verifier runs create NO new version and return the verifier report to the user
        await storage.agent_session_store.put_state(
            session_id,
            state.model_dump(mode="json"),
            expected_etag=etag,
        )
        reason = "; ".join(report.violations)
        return ResumeRefineResult(
            session_id=session_id,
            intent=RefinementIntent.EDIT,
            reply=f"Verifier rejected draft after retries: {reason}",
            current_version=state.current_version,
            artifact=None,
            verifier_report=report,
        )

    new_artifact = await _save_verified_version(
        state,
        expected_etag=etag,
        draft=draft,
        report=report,
        created_by_turn=next_turn_idx,
        storage=storage,
    )
    await storage.agent_session_store.append_turn(
        SessionTurnDoc(
            session_id=session_id,
            turn_index=next_turn_idx + 1,
            role="assistant",
            content=f"Updated resume to v{new_artifact.version}.",
            intent=RefinementIntent.EDIT.value,
            version_after=new_artifact.version,
        )
    )
    return ResumeRefineResult(
        session_id=session_id,
        intent=RefinementIntent.EDIT,
        reply=f"Updated resume to version {new_artifact.version}.",
        current_version=new_artifact.version,
        artifact=new_artifact,
        verifier_report=report,
    )
