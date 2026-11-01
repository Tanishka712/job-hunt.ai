"""R1 CV semantic retrieval tool for the S4 Resume Customizer Agent."""

from app.guardrails.risk import Risk, tool
from app.ports.storage import CVChunk, VectorStore


@tool("search_master_cv", risk=Risk.R1_READ_EXTERNAL)
async def search_master_cv(
    user_id: str,
    query: str,
    *,
    vector_store: VectorStore,
    top_k: int = 5,
) -> list[CVChunk]:
    """Retrieve relevant master CV chunks belonging exclusively to `user_id`."""
    return await vector_store.search(user_id=user_id, query=query, top_k=top_k)
