"""S3 Job Finder workflow: fetch/cache -> parse (LLM) -> verify -> dedupe/score -> persist."""

from app.agents.job_finder.html_cleaner import (
    clean_job_html,
    compute_job_hash,
    normalize_job_url,
)
from app.agents.job_finder.prompts import build_job_extract_prompt
from app.agents.job_finder.schemas import (
    JobIngestRequest,
    JobIngestResult,
    JobIngestStatus,
    JobSpec,
)
from app.agents.job_finder.scorer import compute_match_score
from app.agents.job_finder.tools import HttpFetcher, ScrapeError, scrape_job
from app.core.container import StorageContainer
from app.guardrails.validator import StructuredOutputError
from app.ports.llm import AgentRole, LLMClient
from app.ports.storage import ApplicationRecord, ApplicationStatus


def _verify_job_spec(spec: JobSpec, source_url: str) -> JobSpec | None:
    """Cheap deterministic verifier ensuring parsed JobSpec represents a real job."""
    if not spec.is_job_posting:
        return None
    title = spec.title.strip()
    company = spec.company.strip()
    if not title or not company:
        return None
    if not spec.source_url:
        spec = spec.model_copy(update={"source_url": source_url})
    return spec


async def run_job_finder(
    request: JobIngestRequest,
    *,
    llm: LLMClient,
    storage: StorageContainer,
    fetcher: HttpFetcher | None = None,
) -> JobIngestResult:
    """Execute the S3 Job Finder pipeline for a single job URL or raw HTML snippet."""
    norm_url = normalize_job_url(request.url)

    # Node 1: Check cross-user GlobalJobCacheRepo by normalized URL (saves LLM quota across users)
    cached_spec_dict = await storage.global_job_cache_repo.get(norm_url)
    from_global_cache = False
    verified_spec: JobSpec | None = None

    if cached_spec_dict is not None:
        try:
            candidate = JobSpec.model_validate(cached_spec_dict)
            verified_spec = _verify_job_spec(candidate, request.url)
            if verified_spec is not None:
                from_global_cache = True
        except Exception:
            verified_spec = None

    # Node 2: If cache miss, scrape (R1 tool) or clean raw HTML override, then parse via LLM
    if verified_spec is None:
        if request.raw_html_override is not None:
            cleaned_text = clean_job_html(request.raw_html_override, max_chars=3000)
        else:
            try:
                scraped = await scrape_job(request.url, fetcher=fetcher)
                cleaned_text = scraped.cleaned_text
            except ScrapeError as exc:
                return JobIngestResult(
                    status=JobIngestStatus.FAILED,
                    job_id="failed",
                    job_hash="",
                    url=request.url,
                    user_id=request.user_id,
                    error_reason=str(exc),
                )

        prompt = build_job_extract_prompt(request.url, cleaned_text)
        try:
            parsed_spec = await llm.complete_structured(
                prompt,
                JobSpec,
                role=AgentRole.LIGHTWEIGHT_PARSER,
                retries=2,
                user_api_key=request.user_api_key,
            )
        except StructuredOutputError as exc:
            return JobIngestResult(
                status=JobIngestStatus.FAILED,
                job_id="failed",
                job_hash="",
                url=request.url,
                user_id=request.user_id,
                error_reason=str(exc),
            )

        # Node 3: Verify parsed JobSpec
        verified_spec = _verify_job_spec(parsed_spec, request.url)
        if verified_spec is None:
            return JobIngestResult(
                status=JobIngestStatus.NON_JOB,
                job_id="non-job",
                job_hash="",
                url=request.url,
                user_id=request.user_id,
                error_reason=(
                    "Page is not a valid job posting "
                    "(missing title/company or is_job_posting=false)."
                ),
            )

        # Store in cross-user GlobalJobCacheRepo for 30 days
        await storage.global_job_cache_repo.put(norm_url, verified_spec.model_dump(mode="json"))

    # Node 4: Compute normalized job hash & check per-user 30-day deduplication
    job_hash = compute_job_hash(verified_spec.company, verified_spec.title)
    job_id = f"job-{job_hash[:12]}"

    if await storage.job_hash_repo.exists(request.user_id, job_hash):
        return JobIngestResult(
            status=JobIngestStatus.DUPLICATE,
            job_id=job_id,
            job_hash=job_hash,
            url=request.url,
            user_id=request.user_id,
            job_spec=verified_spec,
            from_global_cache=from_global_cache,
        )

    # Node 5: Compute CV match score against user's VectorStore chunks and ProfileRepo
    query = f"{verified_spec.title} {' '.join(verified_spec.required_skills)}"
    cv_chunks = await storage.vector_store.search(request.user_id, query, top_k=5)
    profile = await storage.profile_repo.get(request.user_id)
    match_score = compute_match_score(verified_spec, cv_chunks, profile)
    qualified = match_score >= request.match_threshold

    # Node 6: Persist hash (30-day TTL) and ApplicationRecord ONLY after successful parse
    await storage.job_hash_repo.put(
        request.user_id,
        job_hash,
        {
            "job_id": job_id,
            "company": verified_spec.company,
            "title": verified_spec.title,
            "url": request.url,
        },
    )
    await storage.application_repo.upsert(
        ApplicationRecord(
            user_id=request.user_id,
            job_id=job_id,
            company=verified_spec.company,
            role_title=verified_spec.title,
            status=ApplicationStatus.FETCHED,
            match_score=match_score,
        )
    )

    return JobIngestResult(
        status=JobIngestStatus.PARSED,
        job_id=job_id,
        job_hash=job_hash,
        url=request.url,
        user_id=request.user_id,
        job_spec=verified_spec,
        match_score=match_score,
        qualified_for_tailoring=qualified,
        from_global_cache=from_global_cache,
    )


async def run_job_finder_batch(
    urls: list[str],
    *,
    user_id: str,
    llm: LLMClient,
    storage: StorageContainer,
    match_threshold: float = 65.0,
    user_api_key: str | None = None,
    fetcher: HttpFetcher | None = None,
) -> list[JobIngestResult]:
    """Process a batch of up to 50 job URLs sequentially with global cache reuse and dedupe."""
    results: list[JobIngestResult] = []
    for url in urls:
        req = JobIngestRequest(
            url=url,
            user_id=user_id,
            match_threshold=match_threshold,
            user_api_key=user_api_key,
        )
        res = await run_job_finder(req, llm=llm, storage=storage, fetcher=fetcher)
        results.append(res)
    return results
