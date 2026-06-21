from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import create_engine, inspect

from company_lens.agent.openai_provider import build_openai_model_provider
from company_lens.agent.persistence import (
    PersistentResearchAgent,
    ResearchSessionManager,
    ResearchSessionRepository,
    postgres_checkpointer,
)
from company_lens.agent.tools import SqlResearchTools
from company_lens.agent.workflow import ResearchAgentRuntime
from company_lens.config import Settings
from company_lens.db.session import build_session_factory
from company_lens.retrieval.embeddings import build_embedder

RESEARCH_SESSION_COLUMNS = {
    "session_id",
    "turn_count",
    "last_run_id",
    "active_run_id",
    "lease_expires_at",
    "expires_at",
    "last_accessed_at",
    "created_at",
    "updated_at",
}


class ResearchApplicationConfigurationError(RuntimeError):
    """Safe configuration failure suitable for application and CLI boundaries."""


def setup_research_persistence(settings: Settings) -> None:
    """Initialize LangGraph-owned tables after the application migration is present."""

    _require_research_session_schema(settings.database_url)
    with postgres_checkpointer(settings.database_url, setup=True):
        pass


@contextmanager
def open_research_session_manager(settings: Settings) -> Iterator[ResearchSessionManager]:
    """Open persistence-only session controls without constructing OpenAI clients."""

    _require_research_session_schema(settings.database_url)
    session_factory = build_session_factory(settings.database_url)
    with postgres_checkpointer(settings.database_url) as checkpointer:
        yield ResearchSessionManager(
            checkpointer=checkpointer,
            session_repository=ResearchSessionRepository(session_factory),
        )


@contextmanager
def open_persistent_research_agent(settings: Settings) -> Iterator[PersistentResearchAgent]:
    """Assemble the production OpenAI, SQL, and PostgreSQL research stack."""

    _require_research_session_schema(settings.database_url)
    model_provider = build_openai_model_provider(settings)
    api_key = (
        settings.openai_api_key.get_secret_value() if settings.openai_api_key is not None else None
    )
    embedder = build_embedder(
        "openai",
        openai_api_key=api_key,
        openai_model=settings.openai_embedding_model,
        dimensions=settings.openai_embedding_dimensions,
        timeout_seconds=settings.openai_request_timeout_seconds,
        max_retries=settings.openai_retry_attempts,
    )
    session_factory = build_session_factory(settings.database_url)
    runtime = ResearchAgentRuntime(
        model_provider=model_provider,
        tools=SqlResearchTools(session_factory=session_factory, embedder=embedder),
        max_session_messages=settings.agent_session_max_messages,
        max_cached_source_results=settings.agent_session_max_cached_results,
        retrieval_index_name=settings.agent_retrieval_index_name,
        retrieval_index_version=settings.agent_retrieval_index_version,
    )
    with postgres_checkpointer(settings.database_url) as checkpointer:
        yield PersistentResearchAgent(
            runtime=runtime,
            checkpointer=checkpointer,
            session_repository=ResearchSessionRepository(session_factory),
            ttl=timedelta(hours=settings.agent_session_ttl_hours),
            lease_duration=timedelta(minutes=settings.agent_session_lease_minutes),
            environment=settings.environment,
        )


def _require_research_session_schema(database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        available_columns = (
            {str(column["name"]) for column in inspector.get_columns("research_sessions")}
            if inspector.has_table("research_sessions")
            else set()
        )
        if not RESEARCH_SESSION_COLUMNS.issubset(available_columns):
            raise ResearchApplicationConfigurationError(
                "Research session schema is missing; run `alembic upgrade head` first."
            )
    except ResearchApplicationConfigurationError:
        raise
    except Exception:
        raise ResearchApplicationConfigurationError(
            "Research database configuration could not be verified."
        ) from None
    finally:
        engine.dispose()
