"""Pydantic schemas for S3 Job Finder Agent, Handoff JobSpec, and Ingest API."""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class SeniorityLevel(StrEnum):
    """Normalized seniority levels for job postings."""

    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    PRINCIPAL = "principal"
    LEAD = "lead"
    UNSPECIFIED = "unspecified"


class RemotePolicy(StrEnum):
    """Normalized workplace remote policies."""

    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNSPECIFIED = "unspecified"


class JobSpec(BaseModel):
    """Typed handoff contract produced by S3 Job Finder Agent."""

    title: str
    company: str
    location: str = "Remote / Unspecified"
    remote_policy: RemotePolicy = RemotePolicy.UNSPECIFIED
    seniority: SeniorityLevel = SeniorityLevel.UNSPECIFIED
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    salary_range: str = ""
    source_url: str = ""
    is_job_posting: bool = True

    @field_validator("seniority", mode="before")
    @classmethod
    def _normalize_seniority(cls, val: object) -> SeniorityLevel:
        if isinstance(val, SeniorityLevel):
            return val
        raw = str(val or "").strip().lower()
        for member in SeniorityLevel:
            if member.value in raw:
                return member
        return SeniorityLevel.UNSPECIFIED

    @field_validator("remote_policy", mode="before")
    @classmethod
    def _normalize_remote_policy(cls, val: object) -> RemotePolicy:
        if isinstance(val, RemotePolicy):
            return val
        raw = str(val or "").strip().lower()
        for member in RemotePolicy:
            if member.value in raw:
                return member
        return RemotePolicy.UNSPECIFIED


class JobIngestStatus(StrEnum):
    """Outcome status of a job ingestion run."""

    PARSED = "PARSED"
    DUPLICATE = "DUPLICATE"
    NON_JOB = "NON_JOB"
    FAILED = "FAILED"


class JobIngestRequest(BaseModel):
    """Input request for ingesting a single job posting."""

    url: str
    user_id: str = "default-user"
    raw_html_override: str | None = None
    match_threshold: float = 65.0
    user_api_key: str | None = None


class BatchJobIngestRequest(BaseModel):
    """Input request for ingesting a batch of up to 50 job URLs."""

    urls: list[str] = Field(min_length=1, max_length=50)
    user_id: str = "default-user"
    match_threshold: float = 65.0
    user_api_key: str | None = None


class JobIngestResult(BaseModel):
    """Output response for a single job ingestion run."""

    status: JobIngestStatus
    job_id: str
    job_hash: str
    url: str
    user_id: str
    job_spec: JobSpec | None = None
    match_score: float = 0.0
    qualified_for_tailoring: bool = False
    from_global_cache: bool = False
    error_reason: str | None = None
