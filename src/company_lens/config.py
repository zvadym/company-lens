from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    openai_planning_model: str = Field(default="gpt-5.4-mini")
    openai_answer_model: str = Field(default="gpt-5.5")
    openai_planning_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "low"
    openai_answer_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "medium"
    openai_planning_max_output_tokens: int = Field(default=2_000, ge=1)
    openai_answer_max_output_tokens: int = Field(default=8_000, ge=1)
    openai_request_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_retry_attempts: int = Field(default=2, ge=0)
    agent_session_ttl_hours: int = Field(default=24, ge=1, le=24 * 365)
    agent_session_max_messages: int = Field(default=20, ge=2, le=1000)
    agent_session_max_cached_results: int = Field(default=20, ge=0, le=1000)
    agent_session_lease_minutes: int = Field(default=15, ge=1, le=24 * 60)
    agent_retrieval_index_name: str = Field(default="default", min_length=1)
    agent_retrieval_index_version: str = Field(
        default="openai-text-embedding-3-small-384.v1",
        min_length=1,
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="COMPANY_LENS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
