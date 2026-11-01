"""Azure Cosmos DB repository adapters implementing storage ports."""

from collections.abc import AsyncIterable
from typing import Any, Protocol

from app.adapters.fakes.storage import SEVEN_DAYS_SECONDS, THIRTY_DAYS_SECONDS
from app.ports.storage import (
    ApplicationRecord,
    ConcurrencyError,
    SessionTurnDoc,
    SessionVersionDoc,
    UserProfile,
)


class AsyncCosmosContainerLike(Protocol):
    """Structural interface for an Azure Cosmos DB async `ContainerProxy`."""

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]: ...

    async def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]: ...

    async def replace_item(
        self,
        item: str,
        body: dict[str, Any],
        *,
        etag: str | None = None,
        match_condition: Any = None,
    ) -> dict[str, Any]: ...

    def query_items(
        self,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
        partition_key: str | None = None,
    ) -> AsyncIterable[dict[str, Any]]: ...


def _is_not_found_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    return status_code == 404 or exc.__class__.__name__ == "CosmosResourceNotFoundError"


def _is_precondition_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    return status_code in (409, 412) or exc.__class__.__name__ in (
        "CosmosAccessConditionFailedError",
        "CosmosResourceExistsError",
    )


class CosmosProfileRepo:
    """Cosmos DB adapter for `profile` container (partition key `/user_id`)."""

    def __init__(self, container: AsyncCosmosContainerLike) -> None:
        self._container = container

    async def get(self, user_id: str) -> UserProfile | None:
        try:
            doc = await self._container.read_item(item=user_id, partition_key=user_id)
        except Exception as exc:
            if _is_not_found_error(exc):
                return None
            raise
        clean = {k: v for k, v in doc.items() if not k.startswith("_") and k != "id"}
        return UserProfile.model_validate(clean)

    async def upsert(self, profile: UserProfile) -> None:
        body = profile.model_dump()
        body["id"] = profile.user_id
        await self._container.upsert_item(body)


class CosmosJobHashRepo:
    """Cosmos DB adapter for `job_hashes` container (`/user_id`, defaultTtl = 30d)."""

    def __init__(
        self,
        container: AsyncCosmosContainerLike,
        default_ttl_seconds: int = THIRTY_DAYS_SECONDS,
    ) -> None:
        self._container = container
        self._default_ttl = default_ttl_seconds

    @property
    def default_ttl_seconds(self) -> int:
        return self._default_ttl

    async def exists(self, user_id: str, job_hash: str) -> bool:
        try:
            await self._container.read_item(item=job_hash, partition_key=user_id)
            return True
        except Exception as exc:
            if _is_not_found_error(exc):
                return False
            raise

    async def put(
        self,
        user_id: str,
        job_hash: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        body = {
            "id": job_hash,
            "user_id": user_id,
            "payload": payload,
            "ttl": ttl,
        }
        await self._container.upsert_item(body)


class CosmosGlobalJobCacheRepo:
    """Cosmos DB adapter for `global_jobs` container (`/job_hash`, defaultTtl = 30d)."""

    def __init__(
        self,
        container: AsyncCosmosContainerLike,
        default_ttl_seconds: int = THIRTY_DAYS_SECONDS,
    ) -> None:
        self._container = container
        self._default_ttl = default_ttl_seconds

    @property
    def default_ttl_seconds(self) -> int:
        return self._default_ttl

    async def get(self, url_or_hash: str) -> dict[str, Any] | None:
        try:
            doc = await self._container.read_item(item=url_or_hash, partition_key=url_or_hash)
            job_spec: dict[str, Any] = doc["job_spec"]
            return job_spec
        except Exception as exc:
            if _is_not_found_error(exc):
                return None
            raise

    async def put(
        self,
        url_or_hash: str,
        job_spec: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        await self._container.upsert_item(
            {
                "id": url_or_hash,
                "job_hash": url_or_hash,
                "job_spec": job_spec,
                "ttl": ttl,
            }
        )


class CosmosCompanyBriefCacheRepo:
    """Cosmos DB adapter for `company_briefs` container (`/company_key`, defaultTtl = 7d)."""

    def __init__(
        self,
        container: AsyncCosmosContainerLike,
        default_ttl_seconds: int = SEVEN_DAYS_SECONDS,
    ) -> None:
        self._container = container
        self._default_ttl = default_ttl_seconds

    @property
    def default_ttl_seconds(self) -> int:
        return self._default_ttl

    async def get(self, normalized_company: str) -> dict[str, Any] | None:
        try:
            doc = await self._container.read_item(
                item=normalized_company, partition_key=normalized_company
            )
            brief: dict[str, Any] = doc["brief"]
            return brief
        except Exception as exc:
            if _is_not_found_error(exc):
                return None
            raise

    async def put(
        self,
        normalized_company: str,
        brief: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        await self._container.upsert_item(
            {
                "id": normalized_company,
                "company_key": normalized_company,
                "brief": brief,
                "ttl": ttl,
            }
        )


class CosmosApplicationRepo:
    """Cosmos DB adapter for `applications` container (`/user_id`)."""

    def __init__(self, container: AsyncCosmosContainerLike) -> None:
        self._container = container

    async def get(self, user_id: str, job_id: str) -> ApplicationRecord | None:
        try:
            doc = await self._container.read_item(item=job_id, partition_key=user_id)
        except Exception as exc:
            if _is_not_found_error(exc):
                return None
            raise
        clean = {k: v for k, v in doc.items() if not k.startswith("_") and k != "id"}
        return ApplicationRecord.model_validate(clean)

    async def upsert(self, record: ApplicationRecord) -> None:
        body = record.model_dump()
        body["id"] = record.job_id
        await self._container.upsert_item(body)

    async def list_by_user(self, user_id: str) -> list[ApplicationRecord]:
        items: list[ApplicationRecord] = []
        query = "SELECT * FROM c WHERE c.user_id = @user_id"
        params = [{"name": "@user_id", "value": user_id}]
        async for doc in self._container.query_items(
            query=query, parameters=params, partition_key=user_id
        ):
            clean = {k: v for k, v in doc.items() if not k.startswith("_") and k != "id"}
            items.append(ApplicationRecord.model_validate(clean))
        return items


class CosmosThreadStore:
    """Cosmos DB adapter for `threads` container (`/thread_id`)."""

    def __init__(self, container: AsyncCosmosContainerLike) -> None:
        self._container = container

    async def get_checkpoint(self, thread_id: str) -> dict[str, Any] | None:
        try:
            doc = await self._container.read_item(item=thread_id, partition_key=thread_id)
            checkpoint: dict[str, Any] = doc["checkpoint"]
            return checkpoint
        except Exception as exc:
            if _is_not_found_error(exc):
                return None
            raise

    async def put_checkpoint(self, thread_id: str, checkpoint: dict[str, Any]) -> None:
        await self._container.upsert_item(
            {"id": thread_id, "thread_id": thread_id, "checkpoint": checkpoint}
        )


class CosmosAgentSessionStore:
    """Cosmos DB adapter for `agent_sessions` container (`/session_id`)."""

    def __init__(self, container: AsyncCosmosContainerLike) -> None:
        self._container = container

    async def get_state(self, session_id: str) -> dict[str, Any] | None:
        state, _ = await self.get_state_with_etag(session_id)
        return state

    async def get_state_with_etag(
        self, session_id: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        try:
            doc = await self._container.read_item(item="state", partition_key=session_id)
            state: dict[str, Any] = doc["state"]
            etag: str | None = doc.get("_etag")
            return state, etag
        except Exception as exc:
            if _is_not_found_error(exc):
                return None, None
            raise

    async def put_state(
        self,
        session_id: str,
        state: dict[str, Any],
        *,
        expected_etag: str | None = None,
    ) -> str:
        body = {
            "id": "state",
            "session_id": session_id,
            "type": "state",
            "state": state,
        }
        try:
            if expected_etag is not None:
                res = await self._container.replace_item(
                    item="state", body=body, etag=expected_etag
                )
            else:
                res = await self._container.upsert_item(body)
        except Exception as exc:
            if _is_precondition_error(exc):
                raise ConcurrencyError(
                    f"ETag precondition failed for session '{session_id}'"
                ) from exc
            raise
        return str(res.get("_etag", ""))

    async def append_turn(self, turn: SessionTurnDoc) -> None:
        body = turn.model_dump()
        body["id"] = f"turn:{turn.turn_index:06d}"
        body["type"] = "turn"
        await self._container.upsert_item(body)

    async def list_turns(self, session_id: str) -> list[SessionTurnDoc]:
        turns: list[SessionTurnDoc] = []
        query = "SELECT * FROM c WHERE c.session_id = @sid AND c.type = 'turn'"
        async for doc in self._container.query_items(
            query=query,
            parameters=[{"name": "@sid", "value": session_id}],
            partition_key=session_id,
        ):
            clean = {
                k: v for k, v in doc.items() if not k.startswith("_") and k not in ("id", "type")
            }
            turns.append(SessionTurnDoc.model_validate(clean))
        return sorted(turns, key=lambda t: t.turn_index)

    async def save_version(self, version_doc: SessionVersionDoc) -> None:
        body = version_doc.model_dump()
        body["id"] = f"version:{version_doc.version:06d}"
        body["type"] = "version"
        await self._container.upsert_item(body)

    async def list_versions(self, session_id: str) -> list[SessionVersionDoc]:
        versions: list[SessionVersionDoc] = []
        query = "SELECT * FROM c WHERE c.session_id = @sid AND c.type = 'version'"
        async for doc in self._container.query_items(
            query=query,
            parameters=[{"name": "@sid", "value": session_id}],
            partition_key=session_id,
        ):
            clean = {
                k: v for k, v in doc.items() if not k.startswith("_") and k not in ("id", "type")
            }
            versions.append(SessionVersionDoc.model_validate(clean))
        return sorted(versions, key=lambda v: v.version)


class CosmosOutreachLogRepo:
    """Cosmos DB adapter for `outreach_log` container (`/user_id`)."""

    def __init__(self, container: AsyncCosmosContainerLike) -> None:
        self._container = container

    async def was_contacted(self, user_id: str, contact_key: str) -> bool:
        try:
            await self._container.read_item(item=contact_key, partition_key=user_id)
            return True
        except Exception as exc:
            if _is_not_found_error(exc):
                return False
            raise

    async def record_contact(
        self, user_id: str, contact_key: str, metadata: dict[str, Any]
    ) -> None:
        await self._container.upsert_item(
            {
                "id": contact_key,
                "user_id": user_id,
                "contact_key": contact_key,
                "metadata": metadata,
            }
        )
