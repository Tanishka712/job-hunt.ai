"""In-memory storage fakes with controllable TTL clock, ETag concurrency, and user isolation."""

import re
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.ports.storage import (
    ApplicationRecord,
    ConcurrencyError,
    CVChunk,
    SASExpiredError,
    SessionTurnDoc,
    SessionVersionDoc,
    UserProfile,
)

THIRTY_DAYS_SECONDS = 2_592_000
SEVEN_DAYS_SECONDS = 604_800


class FakeClock:
    """Controllable monotonic/epoch clock for deterministic TTL and SAS expiry tests."""

    def __init__(self, initial_epoch: float | None = None) -> None:
        self._now = initial_epoch if initial_epoch is not None else time.time()

    def now(self) -> float:
        """Return current simulated epoch timestamp in seconds."""
        return self._now

    def advance(self, seconds: float) -> None:
        """Advance simulated clock by `seconds`."""
        self._now += seconds


class InMemoryProfileRepo:
    """In-memory implementation of ProfileRepo."""

    def __init__(self) -> None:
        self._profiles: dict[str, UserProfile] = {}

    async def get(self, user_id: str) -> UserProfile | None:
        p = self._profiles.get(user_id)
        return p.model_copy(deep=True) if p is not None else None

    async def upsert(self, profile: UserProfile) -> None:
        self._profiles[profile.user_id] = profile.model_copy(deep=True)


class InMemoryJobHashRepo:
    """In-memory implementation of JobHashRepo with 30-day TTL."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        self._clock = clock or FakeClock()
        self._default_ttl = THIRTY_DAYS_SECONDS
        self._entries: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}

    @property
    def default_ttl_seconds(self) -> int:
        return self._default_ttl

    async def exists(self, user_id: str, job_hash: str) -> bool:
        key = (user_id, job_hash)
        entry = self._entries.get(key)
        if entry is None:
            return False
        _, expires_at = entry
        if self._clock.now() >= expires_at:
            del self._entries[key]
            return False
        return True

    async def put(
        self,
        user_id: str,
        job_hash: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expires_at = self._clock.now() + ttl
        self._entries[(user_id, job_hash)] = (dict(payload), expires_at)


class InMemoryGlobalJobCacheRepo:
    """In-memory cross-user 30-day cache for LLM-parsed JobSpecs."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        self._clock = clock or FakeClock()
        self._default_ttl = THIRTY_DAYS_SECONDS
        self._entries: dict[str, tuple[dict[str, Any], float]] = {}

    @property
    def default_ttl_seconds(self) -> int:
        return self._default_ttl

    async def get(self, url_or_hash: str) -> dict[str, Any] | None:
        entry = self._entries.get(url_or_hash)
        if entry is None:
            return None
        payload, expires_at = entry
        if self._clock.now() >= expires_at:
            del self._entries[url_or_hash]
            return None
        return dict(payload)

    async def put(
        self,
        url_or_hash: str,
        job_spec: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        self._entries[url_or_hash] = (dict(job_spec), self._clock.now() + ttl)


class InMemoryCompanyBriefCacheRepo:
    """In-memory cross-user 7-day cache for CompanyBriefs."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        self._clock = clock or FakeClock()
        self._default_ttl = SEVEN_DAYS_SECONDS
        self._entries: dict[str, tuple[dict[str, Any], float]] = {}

    @property
    def default_ttl_seconds(self) -> int:
        return self._default_ttl

    async def get(self, normalized_company: str) -> dict[str, Any] | None:
        entry = self._entries.get(normalized_company)
        if entry is None:
            return None
        payload, expires_at = entry
        if self._clock.now() >= expires_at:
            del self._entries[normalized_company]
            return None
        return dict(payload)

    async def put(
        self,
        normalized_company: str,
        brief: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        self._entries[normalized_company] = (dict(brief), self._clock.now() + ttl)


class InMemoryApplicationRepo:
    """In-memory implementation of ApplicationRepo partitioned by user_id."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ApplicationRecord] = {}

    async def get(self, user_id: str, job_id: str) -> ApplicationRecord | None:
        rec = self._records.get((user_id, job_id))
        return rec.model_copy(deep=True) if rec is not None else None

    async def upsert(self, record: ApplicationRecord) -> None:
        self._records[(record.user_id, record.job_id)] = record.model_copy(deep=True)

    async def list_by_user(self, user_id: str) -> list[ApplicationRecord]:
        return [
            rec.model_copy(deep=True) for (uid, _), rec in self._records.items() if uid == user_id
        ]


class InMemoryThreadStore:
    """In-memory implementation of ThreadStore for LangGraph HITL checkpoints."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, dict[str, Any]] = {}

    async def get_checkpoint(self, thread_id: str) -> dict[str, Any] | None:
        cp = self._checkpoints.get(thread_id)
        return dict(cp) if cp is not None else None

    async def put_checkpoint(self, thread_id: str, checkpoint: dict[str, Any]) -> None:
        self._checkpoints[thread_id] = dict(checkpoint)


class InMemoryAgentSessionStore:
    """In-memory implementation of AgentSessionStore with ETag optimistic concurrency."""

    def __init__(self) -> None:
        self._states: dict[str, tuple[dict[str, Any], str]] = {}
        self._turns: dict[str, list[SessionTurnDoc]] = {}
        self._versions: dict[str, list[SessionVersionDoc]] = {}

    async def get_state(self, session_id: str) -> dict[str, Any] | None:
        entry = self._states.get(session_id)
        return dict(entry[0]) if entry is not None else None

    async def get_state_with_etag(
        self, session_id: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        entry = self._states.get(session_id)
        if entry is None:
            return None, None
        return dict(entry[0]), entry[1]

    async def put_state(
        self,
        session_id: str,
        state: dict[str, Any],
        *,
        expected_etag: str | None = None,
    ) -> str:
        existing = self._states.get(session_id)
        if expected_etag is not None:
            if existing is None or existing[1] != expected_etag:
                raise ConcurrencyError(
                    f"ETag mismatch on session '{session_id}': expected {expected_etag}"
                )
        elif existing is not None:
            raise ConcurrencyError(
                f"Session '{session_id}' already exists; expected_etag required for update"
            )

        new_etag = uuid.uuid4().hex
        self._states[session_id] = (dict(state), new_etag)
        return new_etag

    async def append_turn(self, turn: SessionTurnDoc) -> None:
        turns = self._turns.setdefault(turn.session_id, [])
        turns.append(turn.model_copy(deep=True))

    async def list_turns(self, session_id: str) -> list[SessionTurnDoc]:
        turns = self._turns.get(session_id, [])
        return [t.model_copy(deep=True) for t in sorted(turns, key=lambda x: x.turn_index)]

    async def save_version(self, version_doc: SessionVersionDoc) -> None:
        versions = self._versions.setdefault(version_doc.session_id, [])
        versions.append(version_doc.model_copy(deep=True))

    async def list_versions(self, session_id: str) -> list[SessionVersionDoc]:
        versions = self._versions.get(session_id, [])
        return [v.model_copy(deep=True) for v in sorted(versions, key=lambda x: x.version)]


class InMemoryOutreachLogRepo:
    """In-memory implementation of OutreachLogRepo scoped per user_id."""

    def __init__(self) -> None:
        self._contacted: dict[tuple[str, str], dict[str, Any]] = {}

    async def was_contacted(self, user_id: str, contact_key: str) -> bool:
        return (user_id, contact_key) in self._contacted

    async def record_contact(
        self, user_id: str, contact_key: str, metadata: dict[str, Any]
    ) -> None:
        self._contacted[(user_id, contact_key)] = dict(metadata)


class InMemoryBlobStore:
    """In-memory implementation of BlobStore with read-only expiring SAS URLs."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        self._clock = clock or FakeClock()
        self._blobs: dict[tuple[str, str], tuple[bytes, str]] = {}

    async def upload_bytes(
        self, container: str, blob_path: str, data: bytes, content_type: str
    ) -> str:
        self._blobs[(container, blob_path)] = (bytes(data), content_type)
        return f"https://fakeblob.local/{container}/{blob_path}"

    async def download_bytes(self, container: str, blob_path: str) -> bytes:
        entry = self._blobs.get((container, blob_path))
        if entry is None:
            raise KeyError(f"Blob not found: {container}/{blob_path}")
        return entry[0]

    async def generate_read_sas_url(
        self, container: str, blob_path: str, expires_in_seconds: int = 900
    ) -> str:
        expires_at = int(self._clock.now() + expires_in_seconds)
        return f"https://fakeblob.local/{container}/{blob_path}?sp=r&se={expires_at}&sig=fakesig"

    async def download_via_sas(self, sas_url: str) -> bytes:
        """Helper to validate SAS permissions and expiry in contract tests."""
        parsed = urlparse(sas_url)
        params = parse_qs(parsed.query)
        permissions = params.get("sp", [""])[0]
        if permissions != "r":
            raise PermissionError(f"SAS URL must be read-only (sp=r), got sp={permissions}")
        expires_at = float(params.get("se", ["0"])[0])
        if self._clock.now() >= expires_at:
            raise SASExpiredError(f"SAS URL expired at {expires_at}")

        path_parts = parsed.path.lstrip("/").split("/", 1)
        container, blob_path = path_parts[0], path_parts[1]
        return await self.download_bytes(container, blob_path)


def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9]+", text.lower()) if len(tok) > 1}


class InMemoryVectorStore:
    """In-memory implementation of VectorStore with strict user_id isolation."""

    def __init__(self) -> None:
        self._chunks: dict[tuple[str, str], CVChunk] = {}

    async def upsert_chunks(self, chunks: list[CVChunk]) -> None:
        for chunk in chunks:
            self._chunks[(chunk.user_id, chunk.id)] = chunk.model_copy(deep=True)

    async def search(self, user_id: str, query: str, top_k: int = 5) -> list[CVChunk]:
        query_tokens = _tokenize(query)
        scored: list[tuple[float, CVChunk]] = []

        for (uid, _), chunk in self._chunks.items():
            if uid != user_id:
                continue
            chunk_tokens = _tokenize(chunk.content) | {t.lower() for t in chunk.tags}
            overlap = len(query_tokens & chunk_tokens)
            if overlap > 0:
                score = overlap / max(len(query_tokens), 1)
                scored.append((score, chunk.model_copy(deep=True)))

        scored.sort(key=lambda item: (-item[0], item[1].id))
        return [chunk for _, chunk in scored[:top_k]]
