"""Contract tests for Cosmos, Blob, and AI Search adapters using lightweight SDK proxies."""

import uuid
from collections.abc import AsyncIterable
from typing import Any

import pytest

from app.adapters.blob.store import AzureBlobStore
from app.adapters.cosmos.repos import (
    CosmosAgentSessionStore,
    CosmosApplicationRepo,
    CosmosCompanyBriefCacheRepo,
    CosmosGlobalJobCacheRepo,
    CosmosJobHashRepo,
    CosmosOutreachLogRepo,
    CosmosProfileRepo,
    CosmosThreadStore,
)
from app.adapters.search.vector_store import AzureAISearchVectorStore
from app.core.container import build_in_memory_storage
from app.ports.storage import (
    ApplicationRecord,
    ApplicationStatus,
    ConcurrencyError,
    CVChunk,
    SessionTurnDoc,
    SessionVersionDoc,
    UserProfile,
)


class _NotFoundError(Exception):
    status_code = 404


class _PreconditionFailedError(Exception):
    status_code = 412


class _FakeCosmosContainerProxy:
    """Simulates Azure `ContainerProxy` async methods."""

    def __init__(self, partition_field: str) -> None:
        self._partition_field = partition_field
        self._docs: dict[tuple[str, str], dict[str, Any]] = {}

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        key = (partition_key, item)
        if key not in self._docs:
            raise _NotFoundError(f"Not found: {key}")
        return dict(self._docs[key])

    async def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        pk = str(body[self._partition_field])
        item_id = str(body["id"])
        stored = dict(body)
        stored["_etag"] = uuid.uuid4().hex
        self._docs[(pk, item_id)] = stored
        return dict(stored)

    async def replace_item(
        self,
        item: str,
        body: dict[str, Any],
        *,
        etag: str | None = None,
        match_condition: Any = None,
    ) -> dict[str, Any]:
        pk = str(body[self._partition_field])
        existing = self._docs.get((pk, item))
        if existing is None or (etag is not None and existing.get("_etag") != etag):
            raise _PreconditionFailedError("ETag mismatch")
        stored = dict(body)
        stored["_etag"] = uuid.uuid4().hex
        self._docs[(pk, item)] = stored
        return dict(stored)

    async def query_items(
        self,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
        partition_key: str | None = None,
    ) -> AsyncIterable[dict[str, Any]]:
        for (pk, _), doc in list(self._docs.items()):
            if partition_key is not None and pk != partition_key:
                continue
            if "c.type = 'turn'" in query and doc.get("type") != "turn":
                continue
            if "c.type = 'version'" in query and doc.get("type") != "version":
                continue
            yield dict(doc)


@pytest.mark.contract
async def test_cosmos_repos_contract() -> None:
    """Verify all 8 Cosmos repository adapters against the async container proxy."""
    profile_repo = CosmosProfileRepo(_FakeCosmosContainerProxy("user_id"))
    assert await profile_repo.get("u1") is None
    profile = UserProfile(user_id="u1", full_name="Alan Turing", email="alan@example.com")
    await profile_repo.upsert(profile)
    assert await profile_repo.get("u1") == profile

    hash_repo = CosmosJobHashRepo(_FakeCosmosContainerProxy("user_id"))
    assert hash_repo.default_ttl_seconds == 2_592_000
    assert await hash_repo.exists("u1", "h1") is False
    await hash_repo.put("u1", "h1", {"title": "Cryptanalyst"})
    assert await hash_repo.exists("u1", "h1") is True

    global_cache = CosmosGlobalJobCacheRepo(_FakeCosmosContainerProxy("job_hash"))
    assert global_cache.default_ttl_seconds == 2_592_000
    assert await global_cache.get("url-1") is None
    await global_cache.put("url-1", {"title": "SWE"})
    assert await global_cache.get("url-1") == {"title": "SWE"}

    company_cache = CosmosCompanyBriefCacheRepo(_FakeCosmosContainerProxy("company_key"))
    assert company_cache.default_ttl_seconds == 604_800
    assert await company_cache.get("bletchley") is None
    await company_cache.put("bletchley", {"culture": "Research"})
    assert await company_cache.get("bletchley") == {"culture": "Research"}

    app_repo = CosmosApplicationRepo(_FakeCosmosContainerProxy("user_id"))
    assert await app_repo.get("u1", "j1") is None
    app_rec = ApplicationRecord(
        user_id="u1",
        job_id="j1",
        company="Bletchley",
        role_title="Researcher",
        status=ApplicationStatus.AWAITING_APPROVAL,
    )
    await app_repo.upsert(app_rec)
    assert await app_repo.get("u1", "j1") == app_rec
    assert await app_repo.list_by_user("u1") == [app_rec]

    thread_store = CosmosThreadStore(_FakeCosmosContainerProxy("thread_id"))
    assert await thread_store.get_checkpoint("t1") is None
    await thread_store.put_checkpoint("t1", {"node": "hitl"})
    assert await thread_store.get_checkpoint("t1") == {"node": "hitl"}

    outreach_repo = CosmosOutreachLogRepo(_FakeCosmosContainerProxy("user_id"))
    assert await outreach_repo.was_contacted("u1", "c1") is False
    await outreach_repo.record_contact("u1", "c1", {"role": "Recruiter"})
    assert await outreach_repo.was_contacted("u1", "c1") is True


@pytest.mark.contract
async def test_cosmos_agent_session_store_contract() -> None:
    """Verify CosmosAgentSessionStore state ETag concurrency, turns, and versions."""
    session_store = CosmosAgentSessionStore(_FakeCosmosContainerProxy("session_id"))
    sid = "resume:u1:j1"

    assert await session_store.get_state(sid) is None
    etag1 = await session_store.put_state(sid, {"v": 1})
    state, current_etag = await session_store.get_state_with_etag(sid)
    assert state == {"v": 1}
    assert current_etag == etag1

    with pytest.raises(ConcurrencyError):
        await session_store.put_state(sid, {"v": 2}, expected_etag="wrong-etag")

    etag2 = await session_store.put_state(sid, {"v": 2}, expected_etag=etag1)
    assert etag2 != etag1

    await session_store.append_turn(
        SessionTurnDoc(
            session_id=sid,
            turn_index=1,
            role="user",
            content="Shorten summary",
            intent="edit",
            version_after=2,
        )
    )
    await session_store.save_version(
        SessionVersionDoc(
            session_id=sid,
            version=2,
            content_ref="blob://v2",
            created_by_turn=1,
        )
    )
    assert len(await session_store.list_turns(sid)) == 1
    assert len(await session_store.list_versions(sid)) == 1


class _FakeStream:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def readall(self) -> bytes:
        return self._data


class _FakeBlobClient:
    def __init__(self, url: str, storage: dict[str, bytes]) -> None:
        self._url = url
        self._storage = storage

    @property
    def url(self) -> str:
        return self._url

    async def upload_blob(
        self, data: bytes, *, overwrite: bool = True, content_type: str | None = None
    ) -> None:
        self._storage[self._url] = data

    async def download_blob(self) -> _FakeStream:
        return _FakeStream(self._storage[self._url])


class _FakeBlobServiceClient:
    def __init__(self) -> None:
        self.storage: dict[str, bytes] = {}

    def get_blob_client(self, container: str, blob: str) -> _FakeBlobClient:
        url = f"https://stmint.blob.core.windows.net/{container}/{blob}"
        return _FakeBlobClient(url, self.storage)


class _FakeSearchClient:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []
        self.last_filter: str = ""

    async def upload_documents(self, documents: list[dict[str, Any]]) -> None:
        self.docs.extend(documents)

    async def search(
        self, *, search_text: str, filter: str, top: int = 5
    ) -> AsyncIterable[dict[str, Any]]:
        self.last_filter = filter
        for doc in self.docs[:top]:
            yield {**doc, "@search.score": 1.0}


@pytest.mark.contract
async def test_azure_blob_and_search_adapters_and_container() -> None:
    """Verify AzureBlobStore, AzureAISearchVectorStore OData escaping, and container factory."""
    blob_service = _FakeBlobServiceClient()
    blob_store = AzureBlobStore(
        service_client=blob_service,
        sas_token_builder=lambda c, b, exp: f"sp=r&se={exp}",
    )
    url = await blob_store.upload_bytes(
        "resumes-tailored", "u1/j1/v1.pdf", b"pdf", "application/pdf"
    )
    assert url.endswith("/resumes-tailored/u1/j1/v1.pdf")
    assert await blob_store.download_bytes("resumes-tailored", "u1/j1/v1.pdf") == b"pdf"
    sas = await blob_store.generate_read_sas_url("resumes-tailored", "u1/j1/v1.pdf", 300)
    assert sas.endswith("?sp=r&se=300")

    search_client = _FakeSearchClient()
    vector_store = AzureAISearchVectorStore(search_client)
    chunk = CVChunk(
        id="c1",
        user_id="user'o'connor",
        content="Distributed systems in Go",
        section="experience",
        source="cv.md",
    )
    await vector_store.upsert_chunks([chunk])
    found = await vector_store.search("user'o'connor", "Go systems", top_k=2)
    assert len(found) == 1
    assert search_client.last_filter == "user_id eq 'user''o''connor'"

    container = build_in_memory_storage()
    assert container.job_hash_repo.default_ttl_seconds == 2_592_000
