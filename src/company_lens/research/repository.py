from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from company_lens.db.models import (
    Company,
    CompanyTicker,
    Exchange,
    RateLimitBucket,
    ResearchEvent,
    ResearchFeedback,
    ResearchRun,
)
from company_lens.research.schemas import (
    EVENT_DATA_V2_MODELS,
    CompaniesResponse,
    CompanyOutput,
    FeedbackRequest,
    FeedbackResponse,
    ResearchEventEnvelope,
    ResearchEventType,
    ResearchResult,
    ResearchRunListResponse,
    ResearchRunResponse,
    ResearchRunStatus,
    ResearchSourcesResponse,
    StartResearchRequest,
)


class ResearchRepositoryError(RuntimeError):
    pass


class ActiveResearchRunError(ResearchRepositoryError):
    pass


class ResearchRunNotFoundError(ResearchRepositoryError):
    pass


class RateLimitExceededError(ResearchRepositoryError):
    pass


class ResearchRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def enqueue(
        self,
        request: StartResearchRequest,
        *,
        session_id: str,
        timeout: timedelta,
        now: datetime | None = None,
    ) -> ResearchRun:
        current = now or datetime.now(UTC)
        run = ResearchRun(
            id=uuid.uuid4(),
            session_id=session_id,
            question=request.question,
            policy_json=request.policy.model_dump(mode="json"),
            status=ResearchRunStatus.QUEUED.value,
            queued_at=current,
            deadline_at=current + timeout,
        )
        try:
            with self._session_factory.begin() as session:
                active = session.scalar(
                    select(ResearchRun.id).where(
                        ResearchRun.session_id == session_id,
                        ResearchRun.status.in_(_active_values()),
                    )
                )
                if active is not None:
                    raise ActiveResearchRunError("The research session already has an active run.")
                session.add(run)
                session.flush()
                self._add_event(
                    session,
                    run.id,
                    "run:queued",
                    "run.status",
                    {"status": ResearchRunStatus.QUEUED.value},
                    current,
                )
        except IntegrityError:
            raise ActiveResearchRunError(
                "The research session already has an active run."
            ) from None
        return run

    def get(self, run_id: uuid.UUID) -> ResearchRun | None:
        with self._session_factory() as session:
            return session.get(ResearchRun, run_id)

    def require(self, run_id: uuid.UUID) -> ResearchRun:
        run = self.get(run_id)
        if run is None:
            raise ResearchRunNotFoundError("Research run was not found.")
        return run

    def response(self, run_id: uuid.UUID) -> ResearchRunResponse:
        return _run_response(self.require(run_id))

    def list_session_runs(self, session_id: str, *, limit: int) -> ResearchRunListResponse:
        with self._session_factory() as session:
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(ResearchRun)
                    .where(ResearchRun.session_id == session_id)
                )
                or 0
            )
            rows = session.scalars(
                select(ResearchRun)
                .where(ResearchRun.session_id == session_id)
                .order_by(ResearchRun.queued_at.desc(), ResearchRun.id.desc())
                .limit(limit)
            ).all()
        items = tuple(_run_response(row) for row in reversed(rows))
        return ResearchRunListResponse(items=items, total=total)

    def sources(self, run_id: uuid.UUID) -> ResearchSourcesResponse:
        run = self.require(run_id)
        result = ResearchResult.model_validate(run.result_json) if run.result_json else None
        return ResearchSourcesResponse(
            run_id=run.id,
            sources=result.sources if result is not None else (),
        )

    def request_cancellation(
        self, run_id: uuid.UUID, *, now: datetime | None = None
    ) -> ResearchRunResponse:
        current = now or datetime.now(UTC)
        with self._session_factory.begin() as session:
            run = session.scalar(
                select(ResearchRun).where(ResearchRun.id == run_id).with_for_update()
            )
            if run is None:
                raise ResearchRunNotFoundError("Research run was not found.")
            status = ResearchRunStatus(run.status)
            if status.terminal:
                return _run_response(run)
            run.cancellation_requested_at = run.cancellation_requested_at or current
            if status is ResearchRunStatus.QUEUED:
                run.status = ResearchRunStatus.CANCELLED.value
                run.completed_at = current
                self._add_event(
                    session,
                    run.id,
                    "run:terminal:cancelled",
                    "run.terminal",
                    {"status": ResearchRunStatus.CANCELLED.value},
                    current,
                )
            else:
                run.status = ResearchRunStatus.CANCELLATION_REQUESTED.value
                self._add_event(
                    session,
                    run.id,
                    "run:cancellation_requested",
                    "run.status",
                    {"status": ResearchRunStatus.CANCELLATION_REQUESTED.value},
                    current,
                )
            session.flush()
            return _run_response(run)

    def claim(
        self,
        worker_id: str,
        *,
        lease: timedelta,
        now: datetime | None = None,
    ) -> ResearchRun | None:
        current = now or datetime.now(UTC)
        with self._session_factory.begin() as session:
            run = session.scalar(
                select(ResearchRun)
                .where(
                    or_(
                        ResearchRun.status == ResearchRunStatus.QUEUED.value,
                        and_(
                            ResearchRun.status.in_(
                                (
                                    ResearchRunStatus.RUNNING.value,
                                    ResearchRunStatus.CANCELLATION_REQUESTED.value,
                                )
                            ),
                            or_(
                                ResearchRun.worker_lease_expires_at.is_(None),
                                ResearchRun.worker_lease_expires_at <= current,
                            ),
                        ),
                    )
                )
                .order_by(ResearchRun.queued_at, ResearchRun.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if run is None:
                return None
            if run.status == ResearchRunStatus.CANCELLATION_REQUESTED.value:
                return run
            run.status = ResearchRunStatus.RUNNING.value
            run.started_at = run.started_at or current
            run.worker_id = worker_id
            run.worker_lease_expires_at = current + lease
            self._add_event(
                session,
                run.id,
                "run:running",
                "run.status",
                {"status": ResearchRunStatus.RUNNING.value},
                current,
            )
            session.flush()
            session.expunge(run)
            return run

    def heartbeat(self, run_id: uuid.UUID, worker_id: str, *, lease: timedelta) -> None:
        with self._session_factory.begin() as session:
            run = session.get(ResearchRun, run_id)
            if run is not None and run.worker_id == worker_id:
                run.worker_lease_expires_at = datetime.now(UTC) + lease

    def interruption_reason(self, run_id: uuid.UUID) -> LiteralInterruption | None:
        run = self.require(run_id)
        if run.status == ResearchRunStatus.CANCELLATION_REQUESTED.value:
            return "cancelled"
        if _aware(run.deadline_at) <= datetime.now(UTC):
            return "timed_out"
        return None

    def append_event(
        self,
        run_id: uuid.UUID,
        event_type: ResearchEventType,
        payload: dict[str, object],
        *,
        event_key: str | None = None,
    ) -> None:
        with self._session_factory.begin() as session:
            self._add_event(
                session,
                run_id,
                event_key or f"event:{uuid.uuid4()}",
                event_type,
                payload,
                datetime.now(UTC),
            )

    def events_after(
        self, run_id: uuid.UUID, after_id: int, *, limit: int = 100
    ) -> tuple[ResearchEventEnvelope, ...]:
        self.require(run_id)
        with self._session_factory() as session:
            rows = session.scalars(
                select(ResearchEvent)
                .where(ResearchEvent.run_id == run_id, ResearchEvent.id > after_id)
                .order_by(ResearchEvent.id)
                .limit(limit)
            ).all()
            return tuple(_event_envelope(row) for row in rows)

    def finalize(
        self,
        run_id: uuid.UUID,
        status: ResearchRunStatus,
        *,
        result: ResearchResult | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> ResearchRunResponse:
        if not status.terminal:
            raise ValueError("finalize requires a terminal status")
        current = now or datetime.now(UTC)
        with self._session_factory.begin() as session:
            run = session.scalar(
                select(ResearchRun).where(ResearchRun.id == run_id).with_for_update()
            )
            if run is None:
                raise ResearchRunNotFoundError("Research run was not found.")
            existing = ResearchRunStatus(run.status)
            if existing.terminal:
                return _run_response(run)
            run.status = status.value
            run.result_json = result.model_dump(mode="json") if result is not None else None
            run.error_code = error_code
            run.error_message = error_message
            run.completed_at = current
            run.worker_id = None
            run.worker_lease_expires_at = None
            if result is not None and result.answer is not None:
                for index, chunk in enumerate(_answer_chunks(result.answer)):
                    self._add_event(
                        session,
                        run.id,
                        f"answer:{index}",
                        "answer.token",
                        {"index": index, "delta": chunk},
                        current,
                    )
            self._add_event(
                session,
                run.id,
                f"run:terminal:{status.value}",
                "run.terminal",
                {"status": status.value, "error_code": error_code},
                current,
            )
            session.flush()
            return _run_response(run)

    def create_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        self.require(request.run_id)
        feedback = ResearchFeedback(
            id=uuid.uuid4(),
            run_id=request.run_id,
            rating=request.rating,
            comment=request.comment,
            actor_id=request.actor_id,
            created_at=datetime.now(UTC),
        )
        with self._session_factory.begin() as session:
            session.add(feedback)
        return FeedbackResponse(
            feedback_id=feedback.id,
            run_id=feedback.run_id,
            rating=request.rating,
            created_at=_aware(feedback.created_at),
        )

    def companies(self) -> CompaniesResponse:
        with self._session_factory() as session:
            rows = session.execute(
                select(Company, CompanyTicker, Exchange)
                .outerjoin(
                    CompanyTicker,
                    and_(
                        CompanyTicker.company_id == Company.id,
                        CompanyTicker.is_primary.is_(True),
                        CompanyTicker.valid_to.is_(None),
                    ),
                )
                .outerjoin(Exchange, Exchange.id == CompanyTicker.exchange_id)
                .order_by(Company.display_name, Company.id, CompanyTicker.symbol)
            ).all()
        seen: set[uuid.UUID] = set()
        items: list[CompanyOutput] = []
        for company, ticker, exchange in rows:
            if company.id in seen:
                continue
            seen.add(company.id)
            items.append(
                CompanyOutput(
                    id=company.id,
                    display_name=company.display_name,
                    legal_name=company.legal_name,
                    cik=company.cik,
                    primary_ticker=ticker.symbol if ticker is not None else None,
                    exchange=exchange.code if exchange is not None else None,
                )
            )
        return CompaniesResponse(items=tuple(items), total=len(items))

    def consume_rate_limit(
        self,
        identity: str,
        scope: str,
        *,
        limit: int,
        window_seconds: int,
        now: datetime | None = None,
    ) -> None:
        if limit <= 0:
            return
        current = now or datetime.now(UTC)
        epoch = int(current.timestamp())
        start = datetime.fromtimestamp(epoch - epoch % window_seconds, UTC)
        key = hashlib.sha256(f"{scope}:{identity}".encode()).hexdigest()
        with self._session_factory.begin() as session:
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                statement = (
                    postgresql_insert(RateLimitBucket)
                    .values(
                        bucket_key=key,
                        window_started_at=start,
                        request_count=1,
                        expires_at=start + timedelta(seconds=window_seconds * 2),
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            RateLimitBucket.bucket_key,
                            RateLimitBucket.window_started_at,
                        ],
                        set_={
                            "request_count": RateLimitBucket.request_count + 1,
                            "expires_at": start + timedelta(seconds=window_seconds * 2),
                        },
                        where=RateLimitBucket.request_count < limit,
                    )
                    .returning(RateLimitBucket.request_count)
                )
                if session.execute(statement).scalar_one_or_none() is None:
                    raise RateLimitExceededError("Rate limit exceeded.")
                return
            bucket = session.scalar(
                select(RateLimitBucket)
                .where(
                    RateLimitBucket.bucket_key == key,
                    RateLimitBucket.window_started_at == start,
                )
                .with_for_update()
            )
            if bucket is None:
                bucket = RateLimitBucket(
                    bucket_key=key,
                    window_started_at=start,
                    request_count=0,
                    expires_at=start + timedelta(seconds=window_seconds * 2),
                )
                session.add(bucket)
            if bucket.request_count >= limit:
                raise RateLimitExceededError("Rate limit exceeded.")
            bucket.request_count += 1

    @staticmethod
    def _add_event(
        session: Session,
        run_id: uuid.UUID,
        event_key: str,
        event_type: ResearchEventType,
        payload: dict[str, object],
        occurred_at: datetime,
        schema_version: Literal["1", "2"] = "2",
    ) -> None:
        exists = session.scalar(
            select(ResearchEvent.id).where(
                ResearchEvent.run_id == run_id, ResearchEvent.event_key == event_key
            )
        )
        if exists is None:
            if schema_version == "2":
                model = EVENT_DATA_V2_MODELS.get(event_type)
                if model is None:
                    raise ValueError(f"Unsupported version 2 event type: {event_type}")
                payload = model.model_validate(payload).model_dump(mode="json")
            session.add(
                ResearchEvent(
                    run_id=run_id,
                    event_key=event_key,
                    event_type=event_type,
                    schema_version=schema_version,
                    payload_json=payload,
                    created_at=occurred_at,
                )
            )


LiteralInterruption = Literal["cancelled", "timed_out"]


def _active_values() -> tuple[str, ...]:
    return tuple(
        status.value
        for status in (
            ResearchRunStatus.QUEUED,
            ResearchRunStatus.RUNNING,
            ResearchRunStatus.CANCELLATION_REQUESTED,
        )
    )


def _run_response(run: ResearchRun) -> ResearchRunResponse:
    return ResearchRunResponse(
        run_id=run.id,
        session_id=run.session_id,
        status=ResearchRunStatus(run.status),
        question=run.question,
        result=ResearchResult.model_validate(run.result_json) if run.result_json else None,
        error_code=run.error_code,
        error_message=run.error_message,
        queued_at=_aware(run.queued_at),
        started_at=_aware(run.started_at) if run.started_at else None,
        completed_at=_aware(run.completed_at) if run.completed_at else None,
        deadline_at=_aware(run.deadline_at),
        cancellation_requested_at=(
            _aware(run.cancellation_requested_at) if run.cancellation_requested_at else None
        ),
    )


def _event_envelope(row: ResearchEvent) -> ResearchEventEnvelope:
    return ResearchEventEnvelope(
        id=row.id,
        schema_version=cast(Literal["1", "2"], row.schema_version),
        run_id=row.run_id,
        type=row.event_type,  # type: ignore[arg-type]
        occurred_at=_aware(row.created_at),
        data=row.payload_json,
    )


def _answer_chunks(answer: str, max_chars: int = 120) -> tuple[str, ...]:
    words = answer.split(" ")
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and len(candidate) > max_chars:
            chunks.append(f"{current} ")
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return tuple(chunks)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
