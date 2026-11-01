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
    groq_api_keys: str = ""
    groq_api_key: str = ""

    def parsed_groq_keys(self) -> list[str]:
        """Return list of configured Groq API keys from GROQ_API_KEYS or GROQ_API_KEY."""
        raw = self.groq_api_keys or self.groq_api_key
        return [k.strip() for k in raw.split(",") if k.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
