"""Storage port protocols and domain models (zero external SDK imports)."""

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ConcurrencyError(Exception):
    """Raised when an ETag optimistic concurrency check fails on state update."""


class SASExpiredError(Exception):
    """Raised when attempting to read a blob via an expired SAS URL."""


class ApplicationStatus(StrEnum):
    """Lifecycle status of a job application."""

    FETCHED = "FETCHED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    DRY_RUN_OK = "DRY_RUN_OK"
    DRY_RUN_FAILED = "DRY_RUN_FAILED"
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class UserProfile(BaseModel):
    """Non-secret user profile stored in Cosmos `profile` (/user_id).

    Extra fields (such as passwords or API tokens) are strictly forbidden;
    account credentials live exclusively in Azure Key Vault.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str
    full_name: str
    email: str
    phone: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)


class ApplicationRecord(BaseModel):
    """Episodic job application record stored in Cosmos `applications` (/user_id)."""

    user_id: str
    job_id: str
    company: str
    role_title: str
    status: ApplicationStatus
    match_score: float = 0.0
    edit_history: list[dict[str, Any]] = Field(default_factory=list)


class SessionTurnDoc(BaseModel):
    """Single conversational turn document in `agent_sessions` (/session_id)."""

    session_id: str
    turn_index: int
    role: str
    content: str
    intent: str
    version_after: int | None = None


class SessionVersionDoc(BaseModel):
    """Immutable artifact version document in `agent_sessions` (/session_id)."""

    session_id: str
    version: int
    content_ref: str
    created_by_turn: int
    verifier_report: dict[str, Any] = Field(default_factory=dict)
    parent_version: int | None = None


class CVChunk(BaseModel):
    """Master CV semantic chunk stored in the vector index (`master-cv-chunks`)."""

    id: str
    user_id: str
    content: str
    section: str
    source: str
    tags: list[str] = Field(default_factory=list)
    date: str = ""
    content_vector: list[float] = Field(default_factory=list)


class ProfileRepo(Protocol):
    """Port for reading and writing non-secret user profiles."""

    async def get(self, user_id: str) -> UserProfile | None:
        """Retrieve user profile by user_id."""
        ...

    async def upsert(self, profile: UserProfile) -> None:
        """Create or update user profile."""
        ...


class JobHashRepo(Protocol):
    """Port for per-user 30-day job deduplication hashes (`job_hashes`, /user_id)."""

    @property
    def default_ttl_seconds(self) -> int:
        """Container default TTL in seconds (2,592,000 = 30 days)."""
        ...

    async def exists(self, user_id: str, job_hash: str) -> bool:
        """Check whether user_id has already processed job_hash within TTL."""
        ...

    async def put(
        self,
        user_id: str,
        job_hash: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        """Store job_hash with 30-day TTL."""
        ...


class GlobalJobCacheRepo(Protocol):
    """Port for cross-user 30-day cache of LLM-parsed JobSpecs (`global_jobs`)."""

    @property
    def default_ttl_seconds(self) -> int:
        """Container default TTL in seconds (2,592,000 = 30 days)."""
        ...

    async def get(self, url_or_hash: str) -> dict[str, Any] | None:
        """Retrieve cached JobSpec if present and not expired."""
        ...

    async def put(
        self,
        url_or_hash: str,
        job_spec: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        """Cache parsed JobSpec across users."""
        ...


class CompanyBriefCacheRepo(Protocol):
    """Port for cross-user 7-day cache of researched CompanyBriefs (`company_briefs`)."""

    @property
    def default_ttl_seconds(self) -> int:
        """Container default TTL in seconds (604,800 = 7 days)."""
        ...

    async def get(self, normalized_company: str) -> dict[str, Any] | None:
        """Retrieve cached CompanyBrief if present and not expired."""
        ...

    async def put(
        self,
        normalized_company: str,
        brief: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        """Cache researched CompanyBrief for 7 days across all users."""
        ...


class ApplicationRepo(Protocol):
    """Port for per-user job application records (`applications`, /user_id)."""

    async def get(self, user_id: str, job_id: str) -> ApplicationRecord | None:
        """Retrieve application record for user_id and job_id."""
        ...

    async def upsert(self, record: ApplicationRecord) -> None:
        """Create or update application record."""
        ...

    async def list_by_user(self, user_id: str) -> list[ApplicationRecord]:
        """List all application records belonging to user_id."""
        ...


class ThreadStore(Protocol):
    """Port for LangGraph HITL pause checkpoints (`threads`, /thread_id)."""

    async def get_checkpoint(self, thread_id: str) -> dict[str, Any] | None:
        """Load saved checkpoint by thread_id."""
        ...

    async def put_checkpoint(self, thread_id: str, checkpoint: dict[str, Any]) -> None:
        """Persist checkpoint at HITL gate."""
        ...


class AgentSessionStore(Protocol):
    """Port for isolated Resume and Email conversational sessions (`agent_sessions`)."""

    async def get_state(self, session_id: str) -> dict[str, Any] | None:
        """Load current state document for session_id."""
        ...

    async def get_state_with_etag(
        self, session_id: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Load current state document and its ETag for optimistic concurrency."""
        ...

    async def put_state(
        self,
        session_id: str,
        state: dict[str, Any],
        *,
        expected_etag: str | None = None,
    ) -> str:
        """Write state document, raising ConcurrencyError if expected_etag mismatches."""
        ...

    async def append_turn(self, turn: SessionTurnDoc) -> None:
        """Store a single turn document (`type = 'turn'`)."""
        ...

    async def list_turns(self, session_id: str) -> list[SessionTurnDoc]:
        """List turns ordered by turn_index."""
        ...

    async def save_version(self, version_doc: SessionVersionDoc) -> None:
        """Store an immutable version document (`type = 'version'`)."""
        ...

    async def list_versions(self, session_id: str) -> list[SessionVersionDoc]:
        """List saved versions ordered by version number."""
        ...


class OutreachLogRepo(Protocol):
    """Port for tracking already-approached recruiter contacts (`outreach_log`, /user_id)."""

    async def was_contacted(self, user_id: str, contact_key: str) -> bool:
        """Return True if user_id has already contacted contact_key."""
        ...

    async def record_contact(
        self, user_id: str, contact_key: str, metadata: dict[str, Any]
    ) -> None:
        """Record that user_id approached contact_key."""
        ...


class BlobStore(Protocol):
    """Port for Azure Blob Storage (`resumes-master`, `resumes-tailored`, `screenshots`)."""

    async def upload_bytes(
        self, container: str, blob_path: str, data: bytes, content_type: str
    ) -> str:
        """Upload raw bytes and return the blob URI/path."""
        ...

    async def download_bytes(self, container: str, blob_path: str) -> bytes:
        """Download raw bytes from container/blob_path."""
        ...

    async def generate_read_sas_url(
        self, container: str, blob_path: str, expires_in_seconds: int = 900
    ) -> str:
        """Generate a short-lived, read-only (`sp=r`) SAS URL."""
        ...


class VectorStore(Protocol):
    """Port for user-isolated CV semantic search (`master-cv-chunks`)."""

    async def upsert_chunks(self, chunks: list[CVChunk]) -> None:
        """Idempotently upsert CV chunks by chunk id."""
        ...

    async def search(self, user_id: str, query: str, top_k: int = 5) -> list[CVChunk]:
        """Search chunks belonging exclusively to user_id."""
        ...
