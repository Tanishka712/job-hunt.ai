"""Azure AI Search adapter implementing VectorStore port."""

from collections.abc import AsyncIterable
from typing import Any, Protocol

from app.ports.storage import CVChunk


class AsyncSearchClientLike(Protocol):
    """Structural interface for an Azure AI Search `SearchClient`."""

    async def upload_documents(self, documents: list[dict[str, Any]]) -> Any: ...

    def search(
        self,
        *,
        search_text: str,
        filter: str,
        top: int = 5,
    ) -> AsyncIterable[dict[str, Any]]: ...


def _escape_odata_literal(value: str) -> str:
    """Escape single quotes in OData filter literals to prevent filter injection."""
    return value.replace("'", "''")


class AzureAISearchVectorStore:
    """Azure AI Search adapter enforcing strict `user_id` OData filtering."""

    def __init__(self, search_client: AsyncSearchClientLike) -> None:
        self._client = search_client

    async def upsert_chunks(self, chunks: list[CVChunk]) -> None:
        docs = [chunk.model_dump() for chunk in chunks]
        if docs:
            await self._client.upload_documents(docs)

    async def search(self, user_id: str, query: str, top_k: int = 5) -> list[CVChunk]:
        safe_uid = _escape_odata_literal(user_id)
        odata_filter = f"user_id eq '{safe_uid}'"
        results: list[CVChunk] = []
        async for doc in self._client.search(search_text=query, filter=odata_filter, top=top_k):
            clean = {k: v for k, v in doc.items() if not k.startswith("@search.")}
            results.append(CVChunk.model_validate(clean))
        return results
