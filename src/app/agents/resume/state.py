"""State schema and session ID builder for the S4 Resume Customizer Agent."""

from pydantic import BaseModel, Field, field_validator

from app.ports.storage import CVChunk


def build_resume_session_id(user_id: str, job_id: str) -> str:
    """Construct the canonical isolated session ID for a user's job resume."""
    return f"resume:{user_id}:{job_id}"


class ResumeState(BaseModel):
    """Persistent conversational state for S4 Resume Customizer (`agent_sessions`).

    Messages live as per-turn documents (`SessionTurnDoc`), never inside this object.
    """

    session_id: str
    user_id: str
    job_id: str
    jd_requirements: list[str] = Field(default_factory=list)
    retrieved_chunks: list[CVChunk] = Field(default_factory=list)
    pinned_instructions: list[str] = Field(default_factory=list)
    current_version: int = 0
    summary_of_older_turns: str = ""

    @field_validator("session_id")
    @classmethod
    def _validate_resume_session_prefix(cls, val: str) -> str:
        if not val.startswith("resume:"):
            raise ValueError(f"ResumeState session_id must start with 'resume:', got '{val}'")
        return val
