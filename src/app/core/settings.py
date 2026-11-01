"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed environment settings for MINT Job Hunt AI."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    git_sha: str = "dev"
    environment: str = "local"
    groq_api_key: str = ""
    groq_api_keys: str = ""

    def active_groq_api_key(self) -> str:
        """Return the configured default Groq API key."""
        if self.groq_api_key.strip():
            return self.groq_api_key.strip()
        if self.groq_api_keys.strip():
            return self.groq_api_keys.split(",")[0].strip()
        return ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
