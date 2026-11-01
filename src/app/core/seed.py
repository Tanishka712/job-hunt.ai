"""Idempotent master data seeding for ProfileRepo, BlobStore, and VectorStore."""

from pydantic import BaseModel, Field

from app.ports.storage import BlobStore, CVChunk, ProfileRepo, UserProfile, VectorStore


class MasterSeedInput(BaseModel):
    """Input payload for seeding a user's master profile, resume blob, and CV chunks."""

    profile: UserProfile
    master_resume_bytes: bytes
    master_resume_content_type: str = "text/markdown"
    chunks: list[CVChunk] = Field(default_factory=list)


async def seed_master_data(
    seed: MasterSeedInput,
    profile_repo: ProfileRepo,
    blob_store: BlobStore,
    vector_store: VectorStore,
) -> str:
    """Idempotently load master profile, master resume blob, and chunked CV items."""
    await profile_repo.upsert(seed.profile)

    blob_path = f"{seed.profile.user_id}/master_resume.md"
    blob_uri = await blob_store.upload_bytes(
        "resumes-master",
        blob_path,
        seed.master_resume_bytes,
        content_type=seed.master_resume_content_type,
    )

    if seed.chunks:
        await vector_store.upsert_chunks(seed.chunks)

    return blob_uri


async def seed_user_data(
    *,
    user_id: str,
    profile_repo: ProfileRepo,
    blob_store: BlobStore,
    vector_store: VectorStore,
) -> str:
    """Seed default developer profile and CV chunks for `user_id` (used by CLI and tests)."""
    default_seed = MasterSeedInput(
        profile=UserProfile(
            user_id=user_id,
            full_name="MINT Candidate",
            email=f"{user_id}@example.com",
            phone="+1-555-0199",
            location="Remote",
            links=["https://github.com/Tanishka712"],
            target_roles=[
                "AI Engineer",
                "Senior AI Platform Engineer",
                "Backend Software Engineer",
                "Machine Learning Engineer",
            ],
        ),
        master_resume_bytes=(
            b"# MINT Candidate\n"
            b"Built multi-agent LLM orchestration systems using Python, FastAPI, LangGraph, "
            b"Pydantic, Docker, Azure Cosmos DB, and Azure AI Search."
        ),
        chunks=[
            CVChunk(
                id=f"{user_id}-chunk-1",
                user_id=user_id,
                content=(
                    "Architected multi-agent LLM workflows using Python, FastAPI, LangGraph, "
                    "and Pydantic on Azure Container Apps with Docker."
                ),
                section="experience",
                source="master_cv",
                tags=["Python", "FastAPI", "LangGraph", "Pydantic", "Docker", "Azure"],
                date="2025-2026",
            ),
            CVChunk(
                id=f"{user_id}-chunk-2",
                user_id=user_id,
                content=(
                    "Designed semantic vector search and cross-user caching pipelines on "
                    "Azure AI Search, Azure Cosmos DB, PostgreSQL, Redis, PyTorch, and Kubernetes."
                ),
                section="experience",
                source="master_cv",
                tags=[
                    "Azure Cosmos DB",
                    "Azure AI Search",
                    "PostgreSQL",
                    "Redis",
                    "PyTorch",
                    "Kubernetes",
                ],
                date="2024-2025",
            ),
        ],
    )
    return await seed_master_data(default_seed, profile_repo, blob_store, vector_store)
