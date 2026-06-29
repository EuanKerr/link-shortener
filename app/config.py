from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, read from environment variables."""

    model_config = SettingsConfigDict(case_sensitive=False)

    base_url: str = "http://localhost:8000"
    # Local-dev default; docker-compose.yml overrides with the volume-backed
    # /data/links.db in the container.
    db_path: str = "dev-links.db"

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
