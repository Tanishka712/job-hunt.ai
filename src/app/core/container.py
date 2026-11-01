"""Composition root wiring storage ports to in-memory fakes or Azure adapters."""

from dataclasses import dataclass

from app.adapters.fakes.storage import (
    InMemoryAgentSessionStore,
    InMemoryApplicationRepo,
    InMemoryBlobStore,
    InMemoryCompanyBriefCacheRepo,
    InMemoryGlobalJobCacheRepo,
    InMemoryJobHashRepo,
    InMemoryOutreachLogRepo,
    InMemoryProfileRepo,
    InMemoryThreadStore,
    InMemoryVectorStore,
)
from app.ports.storage import (
    AgentSessionStore,
    ApplicationRepo,
    BlobStore,
    CompanyBriefCacheRepo,
    GlobalJobCacheRepo,
    JobHashRepo,
    OutreachLogRepo,
    ProfileRepo,
    ThreadStore,
    VectorStore,
)


@dataclass(frozen=True)
class StorageContainer:
    """Dependency container holding all storage ports."""

    profile_repo: ProfileRepo
    job_hash_repo: JobHashRepo
    global_job_cache_repo: GlobalJobCacheRepo
    company_brief_cache_repo: CompanyBriefCacheRepo
    application_repo: ApplicationRepo
    thread_store: ThreadStore
    agent_session_store: AgentSessionStore
    outreach_log_repo: OutreachLogRepo
    blob_store: BlobStore
    vector_store: VectorStore


def build_in_memory_storage() -> StorageContainer:
    """Construct a complete StorageContainer backed by in-memory fakes."""
    return StorageContainer(
        profile_repo=InMemoryProfileRepo(),
        job_hash_repo=InMemoryJobHashRepo(),
        global_job_cache_repo=InMemoryGlobalJobCacheRepo(),
        company_brief_cache_repo=InMemoryCompanyBriefCacheRepo(),
        application_repo=InMemoryApplicationRepo(),
        thread_store=InMemoryThreadStore(),
        agent_session_store=InMemoryAgentSessionStore(),
        outreach_log_repo=InMemoryOutreachLogRepo(),
        blob_store=InMemoryBlobStore(),
        vector_store=InMemoryVectorStore(),
    )
