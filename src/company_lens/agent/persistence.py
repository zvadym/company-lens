from __future__ import annotations

import enum
import inspect
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any, Literal, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph.state import CompiledStateGraph
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from company_lens.agent.schemas import (
    AgentError,
    AgentErrorCategory,
    AgentErrorSeverity,
    AgentRunStatus,
    AgentState,
    ExecutionPolicy,
)
from company_lens.agent.workflow import (
    ResearchAgentRuntime,
    build_research_graph,
    create_initial_agent_state,
)
from company_lens.config import Settings
from company_lens.db.models import ResearchSession
from company_lens.db.session import build_session_factory

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
GRAPH_VERSION = "company-lens-research.v1"

InterruptionReason = Literal["cancelled", "timed_out"]


@dataclass(frozen=True)
class AgentExecutionEvent:
    event_type: Literal["node.status", "tool.call", "retrieval.summary", "chart.ready"]
    data: dict[str, str | int | float | bool | None]


class ResearchRunInterrupted(RuntimeError):
    def __init__(self, reason: InterruptionReason, state: AgentState) -> None:
        self.reason = reason
        self.state = state
        super().__init__(f"Research run was {reason}.")


class SessionErrorCode(enum.StrEnum):
    NOT_FOUND = "session_not_found"
    EXPIRED = "session_expired"
    BUSY = "session_busy"
    RESUME_REQUIRED = "session_resume_required"
    NOT_RESUMABLE = "session_not_resumable"
    PERSISTENCE = "session_persistence_failed"


class ResearchSessionError(RuntimeError):
    def __init__(self, code: SessionErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class ResearchSessionMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    turn_count: int
    last_run_id: uuid.UUID | None
    active_run_id: uuid.UUID | None
    lease_expires_at: datetime | None
    expires_at: datetime
    last_accessed_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ResearchSessionSnapshot:
    metadata: ResearchSessionMetadata
    state: AgentState
    checkpoint_id: str | None
    pending_nodes: tuple[str, ...]
    resumable: bool


class ResearchSessionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, session_id: str) -> ResearchSessionMetadata | None:
        with self._session_factory() as session:
            row = session.get(ResearchSession, session_id)
            return _metadata(row) if row is not None else None

    def ensure(self, session_id: str, *, now: datetime, expires_at: datetime) -> None:
        with self._session_factory.begin() as session:
            row = session.get(ResearchSession, session_id)
            if row is None:
                session.add(
                    ResearchSession(
                        session_id=session_id,
                        expires_at=expires_at,
                        last_accessed_at=now,
                    )
                )

    def acquire(
        self,
        session_id: str,
        run_id: uuid.UUID,
        *,
        now: datetime,
        lease_expires_at: datetime,
        allow_same_run_takeover: bool = False,
    ) -> None:
        with self._session_factory.begin() as session:
            row = session.scalar(
                select(ResearchSession)
                .where(ResearchSession.session_id == session_id)
                .with_for_update()
            )
            if row is None:
                raise ResearchSessionError(
                    SessionErrorCode.NOT_FOUND, "Research session does not exist."
                )
            if (
                row.active_run_id is not None
                and row.lease_expires_at is not None
                and _aware(row.lease_expires_at) > now
                and not (allow_same_run_takeover and row.active_run_id == run_id)
            ):
                raise ResearchSessionError(
                    SessionErrorCode.BUSY, "Research session already has an active run."
                )
            row.active_run_id = run_id
            row.lease_expires_at = lease_expires_at
            row.last_accessed_at = now

    def renew(
        self,
        session_id: str,
        run_id: uuid.UUID,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> None:
        with self._session_factory.begin() as session:
            row = session.get(ResearchSession, session_id)
            if row is None or row.active_run_id != run_id:
                raise ResearchSessionError(
                    SessionErrorCode.PERSISTENCE, "Research session lease could not be renewed."
                )
            row.lease_expires_at = lease_expires_at
            row.last_accessed_at = now

    def release(
        self,
        session_id: str,
        run_id: uuid.UUID,
        *,
        now: datetime,
        expires_at: datetime,
        increment_turn: bool,
    ) -> None:
        with self._session_factory.begin() as session:
            row = session.get(ResearchSession, session_id)
            if row is None or row.active_run_id != run_id:
                raise ResearchSessionError(
                    SessionErrorCode.PERSISTENCE, "Research session lease could not be released."
                )
            row.active_run_id = None
            row.lease_expires_at = None
            row.last_run_id = run_id
            row.last_accessed_at = now
            row.expires_at = expires_at
            if increment_turn:
                row.turn_count += 1

    def delete(self, session_id: str) -> bool:
        with self._session_factory.begin() as session:
            row = session.get(ResearchSession, session_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def expired_ids(self, *, now: datetime, limit: int) -> tuple[str, ...]:
        with self._session_factory() as session:
            return tuple(
                session.scalars(
                    select(ResearchSession.session_id)
                    .where(
                        ResearchSession.expires_at <= now,
                        or_(
                            ResearchSession.active_run_id.is_(None),
                            ResearchSession.lease_expires_at <= now,
                        ),
                    )
                    .order_by(ResearchSession.expires_at, ResearchSession.session_id)
                    .limit(limit)
                ).all()
            )


class ResearchSessionManager:
    """Manage persisted research sessions without requiring model or tool providers."""

    def __init__(
        self,
        *,
        checkpointer: BaseCheckpointSaver[str],
        session_repository: ResearchSessionRepository,
        graph: CompiledStateGraph[AgentState, ResearchAgentRuntime, AgentState, AgentState]
        | None = None,
    ) -> None:
        self._checkpointer = checkpointer
        self._repository = session_repository
        self._graph = graph or build_research_graph(checkpointer)

    def inspect_session(self, session_id: str) -> ResearchSessionSnapshot | None:
        _validate_session_id(session_id)
        metadata = self._repository.get(session_id)
        if metadata is None:
            return None
        snapshot = self._graph.get_state(_thread_config(session_id))
        configurable = snapshot.config.get("configurable", {})
        checkpoint_id = configurable.get("checkpoint_id")
        return ResearchSessionSnapshot(
            metadata=metadata,
            state=cast(AgentState, snapshot.values),
            checkpoint_id=str(checkpoint_id) if checkpoint_id else None,
            pending_nodes=tuple(snapshot.next),
            resumable=bool(snapshot.next) and not _lease_active(metadata, datetime.now(UTC)),
        )

    def clear_session(self, session_id: str) -> bool:
        _validate_session_id(session_id)
        metadata = self._repository.get(session_id)
        if metadata is None:
            return False
        if _lease_active(metadata, datetime.now(UTC)):
            raise ResearchSessionError(
                SessionErrorCode.BUSY, "Active research session cannot be cleared."
            )
        return self._delete_session(session_id)

    def expire_sessions(self, *, now: datetime | None = None, limit: int = 100) -> int:
        if limit < 1:
            raise ValueError("Expiry cleanup limit must be positive.")
        current = now or datetime.now(UTC)
        expired = self._repository.expired_ids(now=current, limit=limit)
        return sum(self._delete_session(session_id) for session_id in expired)

    def _delete_session(self, session_id: str) -> bool:
        self._checkpointer.delete_thread(session_id)
        return self._repository.delete(session_id)


class PersistentResearchAgent:
    def __init__(
        self,
        *,
        runtime: ResearchAgentRuntime,
        checkpointer: BaseCheckpointSaver[str],
        session_repository: ResearchSessionRepository,
        ttl: timedelta = timedelta(hours=24),
        lease_duration: timedelta = timedelta(minutes=15),
        environment: str = "local",
        graph: CompiledStateGraph[AgentState, ResearchAgentRuntime, AgentState, AgentState]
        | None = None,
    ) -> None:
        self._runtime = runtime
        self._checkpointer = checkpointer
        self._repository = session_repository
        self._ttl = ttl
        self._lease_duration = lease_duration
        self._environment = environment
        self._graph = graph or build_research_graph(checkpointer)
        self._session_manager = ResearchSessionManager(
            checkpointer=checkpointer,
            session_repository=session_repository,
            graph=self._graph,
        )

    def run(
        self,
        question: str,
        *,
        session_id: str,
        policy: ExecutionPolicy | None = None,
        run_id: uuid.UUID | None = None,
        observer: Callable[[AgentExecutionEvent], None] | None = None,
        control: Callable[[], InterruptionReason | None] | None = None,
        allow_run_takeover: bool = False,
    ) -> AgentState:
        _validate_session_id(session_id)
        now = datetime.now(UTC)
        active_run_id = run_id or uuid.uuid4()
        state = create_initial_agent_state(
            question,
            session_id=session_id,
            policy=policy,
            run_id=active_run_id,
        )
        state.pop("session_memory", None)
        metadata = self._repository.get(session_id)
        if metadata is not None and metadata.expires_at <= now:
            if _lease_active(metadata, now):
                raise ResearchSessionError(
                    SessionErrorCode.BUSY, "Expired session still has an active run lease."
                )
            self._delete_session(session_id)
            metadata = None
        if metadata is None:
            self._repository.ensure(session_id, now=now, expires_at=now + self._ttl)
        snapshot = self._graph.get_state(_thread_config(session_id))
        if snapshot.next:
            raise ResearchSessionError(
                SessionErrorCode.RESUME_REQUIRED,
                "Research session has an unfinished run that must be resumed or cleared.",
            )
        self._acquire(
            session_id,
            active_run_id,
            now,
            allow_same_run_takeover=allow_run_takeover,
        )
        return self._execute(
            state,
            session_id=session_id,
            run_id=active_run_id,
            observer=observer,
            control=control,
        )

    def resume(
        self,
        session_id: str,
        *,
        observer: Callable[[AgentExecutionEvent], None] | None = None,
        control: Callable[[], InterruptionReason | None] | None = None,
        allow_run_takeover: bool = False,
    ) -> AgentState:
        _validate_session_id(session_id)
        now = datetime.now(UTC)
        metadata = self._require_metadata(session_id)
        if metadata.expires_at <= now:
            raise ResearchSessionError(SessionErrorCode.EXPIRED, "Research session has expired.")
        snapshot = self._graph.get_state(_thread_config(session_id))
        if not snapshot.next:
            raise ResearchSessionError(
                SessionErrorCode.NOT_RESUMABLE, "Research session has no pending graph nodes."
            )
        state = cast(AgentState, snapshot.values)
        run_id = state["run_id"]
        self._acquire(
            session_id,
            run_id,
            now,
            allow_same_run_takeover=allow_run_takeover,
        )
        return self._execute(
            None,
            session_id=session_id,
            run_id=run_id,
            observer=observer,
            control=control,
        )

    def inspect_session(self, session_id: str) -> ResearchSessionSnapshot | None:
        return self._session_manager.inspect_session(session_id)

    def clear_session(self, session_id: str) -> bool:
        return self._session_manager.clear_session(session_id)

    def expire_sessions(self, *, now: datetime | None = None, limit: int = 100) -> int:
        return self._session_manager.expire_sessions(now=now, limit=limit)

    def _execute(
        self,
        graph_input: AgentState | None,
        *,
        session_id: str,
        run_id: uuid.UUID,
        observer: Callable[[AgentExecutionEvent], None] | None,
        control: Callable[[], InterruptionReason | None] | None,
    ) -> AgentState:
        config = _thread_config(
            session_id,
            run_id=run_id,
            environment=self._environment,
        )
        latest: AgentState | None = None
        previous: AgentState | None = None
        interruption: InterruptionReason | None = None
        stream = self._graph.stream(
            graph_input,
            config=config,
            context=self._runtime,
            stream_mode="values",
        )
        try:
            for value in stream:
                latest = cast(AgentState, value)
                _emit_execution_events(previous, latest, observer)
                previous = latest
                now = datetime.now(UTC)
                self._repository.renew(
                    session_id,
                    run_id,
                    now=now,
                    lease_expires_at=now + self._lease_duration,
                )
                interruption = control() if control is not None else None
                if interruption is not None:
                    break
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        if interruption is not None:
            interrupted_state = self._abort_execution(
                config,
                session_id=session_id,
                run_id=run_id,
                reason=interruption,
            )
            raise ResearchRunInterrupted(interruption, interrupted_state)
        if latest is None:
            latest = cast(AgentState, self._graph.get_state(config).values)
        now = datetime.now(UTC)
        pending = bool(self._graph.get_state(config).next)
        expires_at = self._require_metadata(session_id).expires_at if pending else now + self._ttl
        self._repository.release(
            session_id,
            run_id,
            now=now,
            expires_at=expires_at,
            increment_turn=not pending,
        )
        return latest

    def _abort_execution(
        self,
        config: RunnableConfig,
        *,
        session_id: str,
        run_id: uuid.UUID,
        reason: InterruptionReason,
    ) -> AgentState:
        code = "research_cancelled" if reason == "cancelled" else "research_timed_out"
        message = (
            "Research run was cancelled."
            if reason == "cancelled"
            else "Research run exceeded its execution deadline."
        )
        self._graph.update_state(
            config,
            {
                "status": AgentRunStatus.FAILED,
                "final_answer": None,
                "errors": (
                    AgentError(
                        category=AgentErrorCategory.BUDGET,
                        severity=AgentErrorSeverity.TERMINAL,
                        code=code,
                        message=message,
                    ),
                ),
            },
            as_node="finalize_response",
        )
        state = cast(AgentState, self._graph.get_state(config).values)
        now = datetime.now(UTC)
        self._repository.release(
            session_id,
            run_id,
            now=now,
            expires_at=now + self._ttl,
            increment_turn=True,
        )
        return state

    def _acquire(
        self,
        session_id: str,
        run_id: uuid.UUID,
        now: datetime,
        *,
        allow_same_run_takeover: bool = False,
    ) -> None:
        self._repository.acquire(
            session_id,
            run_id,
            now=now,
            lease_expires_at=now + self._lease_duration,
            allow_same_run_takeover=allow_same_run_takeover,
        )

    def _require_metadata(self, session_id: str) -> ResearchSessionMetadata:
        metadata = self._repository.get(session_id)
        if metadata is None:
            raise ResearchSessionError(
                SessionErrorCode.NOT_FOUND, "Research session does not exist."
            )
        return metadata

    def _delete_session(self, session_id: str) -> bool:
        return self._session_manager._delete_session(session_id)


def build_persistent_research_agent(
    settings: Settings,
    *,
    runtime: ResearchAgentRuntime,
    checkpointer: BaseCheckpointSaver[str],
) -> PersistentResearchAgent:
    configured_runtime = replace(
        runtime,
        max_session_messages=settings.agent_session_max_messages,
        max_cached_source_results=settings.agent_session_max_cached_results,
    )
    return PersistentResearchAgent(
        runtime=configured_runtime,
        checkpointer=checkpointer,
        session_repository=ResearchSessionRepository(build_session_factory(settings.database_url)),
        ttl=timedelta(hours=settings.agent_session_ttl_hours),
        lease_duration=timedelta(minutes=settings.agent_session_lease_minutes),
        environment=settings.environment,
    )


@contextmanager
def postgres_checkpointer(
    database_url: str,
    *,
    setup: bool = False,
) -> Iterator[PostgresSaver]:
    serializer = checkpoint_serializer()
    pool: ConnectionPool[Connection[dict[str, Any]]] = ConnectionPool(
        conninfo=_psycopg_url(database_url),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    try:
        saver = PostgresSaver(pool, serde=serializer)
        if setup:
            saver.setup()
        yield saver
    finally:
        pool.close()


def checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=_checkpoint_type_allowlist(),
    )


def _checkpoint_type_allowlist() -> tuple[tuple[str, ...], ...]:
    modules = (
        "company_lens.agent.schemas",
        "company_lens.analytics.schemas",
        "company_lens.evidence.schemas",
        "company_lens.financials.schemas",
        "company_lens.macro.schemas",
        "company_lens.retrieval.adaptive_schemas",
        "company_lens.retrieval.schemas",
    )
    result: list[tuple[str, ...]] = []
    for module_name in modules:
        module = import_module(module_name)
        result.extend(
            (module_name, value.__qualname__)
            for value in vars(module).values()
            if inspect.isclass(value) and value.__module__ == module_name
        )
    return tuple(sorted(set(result)))


def _thread_config(
    session_id: str,
    *,
    run_id: uuid.UUID | None = None,
    environment: str | None = None,
) -> RunnableConfig:
    config: RunnableConfig = {"configurable": {"thread_id": session_id}}
    if run_id is not None:
        config["run_id"] = run_id
        config["tags"] = ["company-lens", GRAPH_VERSION]
        config["metadata"] = {
            "session_id": session_id,
            "run_id": str(run_id),
            "environment": environment or "unknown",
            "graph_version": GRAPH_VERSION,
        }
    return config


def _emit_execution_events(
    previous: AgentState | None,
    current: AgentState,
    observer: Callable[[AgentExecutionEvent], None] | None,
) -> None:
    if observer is None:
        return
    old_trajectory = previous.get("trajectory", ()) if previous is not None else ()
    for event in current.get("trajectory", ())[len(old_trajectory) :]:
        observer(
            AgentExecutionEvent(
                event_type="node.status",
                data={
                    "node": event.node,
                    "status": event.status.value,
                    "summary": event.summary,
                    "duration_ms": event.duration_ms,
                },
            )
        )
    old_outcomes = previous.get("branch_outcomes", ()) if previous is not None else ()
    for outcome in current.get("branch_outcomes", ())[len(old_outcomes) :]:
        observer(
            AgentExecutionEvent(
                event_type="tool.call",
                data={
                    "branch_id": outcome.branch_id,
                    "kind": outcome.kind,
                    "status": outcome.status.value,
                    "attempts": outcome.attempts,
                    "error_code": outcome.error.code if outcome.error is not None else None,
                },
            )
        )
    old_retrieval = previous.get("retrieval_results", ()) if previous is not None else ()
    for retrieval in current.get("retrieval_results", ())[len(old_retrieval) :]:
        observer(
            AgentExecutionEvent(
                event_type="retrieval.summary",
                data={
                    "branch_id": retrieval.branch_id,
                    "passages": len(retrieval.result.context),
                },
            )
        )
    previous_chart = previous.get("chart_spec") if previous is not None else None
    chart = current.get("chart_spec")
    if previous_chart is None and chart is not None:
        observer(
            AgentExecutionEvent(
                event_type="chart.ready",
                data={"chart_type": chart.chart_type, "title": chart.title},
            )
        )


def _metadata(row: ResearchSession) -> ResearchSessionMetadata:
    return ResearchSessionMetadata(
        session_id=row.session_id,
        turn_count=row.turn_count,
        last_run_id=row.last_run_id,
        active_run_id=row.active_run_id,
        lease_expires_at=_aware(row.lease_expires_at) if row.lease_expires_at else None,
        expires_at=_aware(row.expires_at),
        last_accessed_at=_aware(row.last_accessed_at),
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
    )


def _lease_active(metadata: ResearchSessionMetadata, now: datetime) -> bool:
    return (
        metadata.active_run_id is not None
        and metadata.lease_expires_at is not None
        and metadata.lease_expires_at > now
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _validate_session_id(session_id: str) -> None:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("session_id must be a safe identifier of at most 128 characters.")


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)
