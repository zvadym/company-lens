from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="COMPANY_LENS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
