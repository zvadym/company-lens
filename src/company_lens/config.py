from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = Field(default="local")
    log_level: str = Field(default="INFO")
    database_url: str = Field(
        default="postgresql+psycopg://company_lens:company_lens@localhost:5432/company_lens"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="COMPANY_LENS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
