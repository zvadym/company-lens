from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = Field(default="local")
    log_level: str = Field(default="INFO")
    database_url: str = Field(
        default="postgresql+psycopg://company_lens:company_lens@localhost:5432/company_lens"
    )
    sec_user_agent: str | None = Field(default=None)
    sec_artifact_root: Path = Field(default=Path("data/sec-artifacts"))
    sec_rate_limit_per_second: float = Field(default=9.0)
    sec_request_timeout_seconds: float = Field(default=30.0)
    sec_retry_attempts: int = Field(default=3)
    sec_filings_per_form: int = Field(default=3)
    sec_download_exhibits: bool = Field(default=False)
    investor_pdf_manifest_path: Path = Field(default=Path("config/investor_pdfs.yaml"))
    investor_pdf_artifact_root: Path = Field(default=Path("data/investor-pdf-artifacts"))
    investor_pdf_user_agent: str = Field(default="CompanyLens PDF ingestion")
    investor_pdf_request_timeout_seconds: float = Field(default=30.0)
    investor_pdf_retry_attempts: int = Field(default=3)
    fred_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COMPANY_LENS_FRED_API_KEY", "FRED_API_KEY"),
    )
    fred_base_url: str = Field(default="https://api.stlouisfed.org/fred")
    fred_request_timeout_seconds: float = Field(default=30.0)
    fred_retry_attempts: int = Field(default=3)
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "COMPANY_LENS_OPENAI_API_KEY"),
    )
    openai_embedding_model: str = Field(default="text-embedding-3-small")
    openai_embedding_dimensions: int = Field(default=384, ge=1)
    openai_request_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_retry_attempts: int = Field(default=2, ge=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="COMPANY_LENS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
