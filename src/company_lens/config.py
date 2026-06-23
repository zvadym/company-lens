from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = Field(default="local")
    log_level: str = Field(default="INFO")
    service_name: str = Field(default="company-lens", min_length=1)
    service_version: str = Field(default="0.1.0", min_length=1)
    telemetry_enabled: bool = Field(default=True)
    metrics_enabled: bool = Field(default=True)
    trace_content: Literal["metadata", "redacted", "full"] = Field(default="metadata")
    langfuse_public_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COMPANY_LENS_LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY"),
    )
    langfuse_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("COMPANY_LENS_LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY"),
    )
    langfuse_base_url: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("COMPANY_LENS_LANGFUSE_BASE_URL", "LANGFUSE_BASE_URL"),
    )
    prompt_version: str = Field(default="research-v1", min_length=1)
    parser_version: str = Field(default="document-parser-v1", min_length=1)
    database_url: str = Field(
        default="postgresql+psycopg://company_lens:company_lens@localhost:5432/company_lens"
    )
    sec_user_agent: str | None = Field(default=None)
    sec_artifact_root: Path = Field(default=Path("data/sec-artifacts"))
    sec_rate_limit_per_second: float = Field(default=9.0)
    sec_request_timeout_seconds: float = Field(default=30.0)
    sec_retry_attempts: int = Field(default=3)
    sec_max_response_bytes: int = Field(default=50 * 1024 * 1024, ge=1_024)
    sec_filings_per_form: int = Field(default=3)
    sec_download_exhibits: bool = Field(default=False)
    investor_pdf_manifest_path: Path = Field(default=Path("config/investor_pdfs.yaml"))
    investor_pdf_artifact_root: Path = Field(default=Path("data/investor-pdf-artifacts"))
    investor_pdf_user_agent: str = Field(default="CompanyLens PDF ingestion")
    investor_pdf_request_timeout_seconds: float = Field(default=30.0)
    investor_pdf_retry_attempts: int = Field(default=3)
    investor_pdf_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1_024)
    investor_pdf_allowed_hosts: tuple[str, ...] = (
        "cloudflare2019ipo.q4web.com",
        "www.annualreports.com",
        "s26.q4cdn.com",
        "stocklight.com",
    )
    fred_api_key: SecretStr | None = Field(
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
    openai_repair_model: str = Field(default="gpt-5.4-mini", min_length=1)
    semantic_judge_enabled: bool = Field(default=False)
    semantic_judge_model: str = Field(default="gpt-5.4-mini", min_length=1)
    semantic_judge_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "low"
    semantic_judge_max_output_tokens: int = Field(default=512, ge=1)
    openai_planning_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "low"
    openai_answer_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "medium"
    openai_repair_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "low"
    openai_planning_max_output_tokens: int = Field(default=2_000, ge=1)
    openai_answer_max_output_tokens: int = Field(default=8_000, ge=1)
    openai_repair_max_output_tokens: int = Field(default=3_000, ge=1)
    openai_request_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_repair_timeout_seconds: float = Field(default=30.0, gt=0)
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
    research_run_timeout_seconds: int = Field(default=600, ge=10, le=24 * 60 * 60)
    research_worker_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    research_worker_lease_seconds: int = Field(default=60, ge=10, le=60 * 60)
    research_sse_poll_seconds: float = Field(default=0.25, gt=0, le=10)
    research_sse_heartbeat_seconds: float = Field(default=15.0, gt=0, le=120)
    api_max_body_bytes: int = Field(default=16_384, ge=1_024, le=10 * 1024 * 1024)
    research_question_max_chars: int = Field(default=4_000, ge=1, le=4_000)
    feedback_comment_max_chars: int = Field(default=2_000, ge=1, le=2_000)
    research_start_rate_limit_per_minute: int = Field(default=10, ge=0, le=10_000)
    feedback_rate_limit_per_minute: int = Field(default=30, ge=0, le=10_000)
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1, le=100)
    circuit_breaker_recovery_seconds: float = Field(default=30.0, gt=0, le=3600)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="COMPANY_LENS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
