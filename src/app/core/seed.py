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
