from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from company_lens.agent.persistence import AgentExecutionEvent, InterruptionReason
from company_lens.agent.schemas import AgentRunStatus, AgentState
from company_lens.db.models import ResearchEvent, ResearchFeedback, ResearchRun
from company_lens.research.repository import ResearchRunRepository
from company_lens.research.schemas import ResearchRunStatus, StartResearchRequest
from company_lens.research.worker import ResearchWorker

TABLES = (ResearchRun.__table__, ResearchEvent.__table__, ResearchFeedback.__table__)


class FakeAgent:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def inspect_session(self, session_id: str) -> None:
        del session_id
        return None

    def run(
        self,
        question: str,
        *,
        session_id: str,
        policy: object,
        run_id: uuid.UUID,
        observer: Callable[[AgentExecutionEvent], None],
        control: Callable[[], InterruptionReason | None],
        allow_run_takeover: bool,
    ) -> AgentState:
        del question, policy, allow_run_takeover
        observer(
            AgentExecutionEvent(
                event_type="node.status",
                data={"node": "finalize_response", "status": "completed"},
            )
        )
        assert control() is None
        if self.fail:
            raise RuntimeError("private stack detail")
        return _completed_state(session_id, run_id)


def test_worker_persists_validated_answer_events_and_result() -> None:
    repository = _repository()
    run = repository.enqueue(
        StartResearchRequest(question="Question"),
        session_id="worker-session",
        timeout=timedelta(minutes=10),
    )
    worker = ResearchWorker(
        repository=repository,
        agent=FakeAgent(),  # type: ignore[arg-type]
        worker_id="worker-1",
    )

    assert worker.run_once() is True
    response = repository.response(run.id)
    assert response.status is ResearchRunStatus.COMPLETED
    assert response.result is not None
    assert response.result.answer == "Validated answer."
    events = repository.events_after(run.id, 0)
    assert [event.type for event in events] == [
        "run.status",
        "run.status",
        "node.status",
        "answer.token",
        "run.terminal",
    ]
    assert "UNVALIDATED" not in "".join(str(event.data) for event in events)


def test_worker_timeout_and_safe_failure() -> None:
    repository = _repository()
    old = datetime.now(UTC) - timedelta(minutes=5)
    timed_out = repository.enqueue(
        StartResearchRequest(question="Slow"),
        session_id="timeout-session",
        timeout=timedelta(seconds=1),
        now=old,
    )
    worker = ResearchWorker(
        repository=repository,
        agent=FakeAgent(),  # type: ignore[arg-type]
        worker_id="worker-timeout",
    )
    assert worker.run_once() is True
    assert repository.response(timed_out.id).status is ResearchRunStatus.TIMED_OUT

    failed = repository.enqueue(
        StartResearchRequest(question="Fail"),
        session_id="failure-session",
        timeout=timedelta(minutes=10),
    )
    failing_worker = ResearchWorker(
        repository=repository,
        agent=FakeAgent(fail=True),  # type: ignore[arg-type]
        worker_id="worker-failure",
    )
    assert failing_worker.run_once() is True
    response = repository.response(failed.id)
    assert response.status is ResearchRunStatus.FAILED
    assert response.error_message == "The research run could not be completed."
    assert "private" not in response.error_message


def test_claim_uses_worker_lease_for_recovery() -> None:
    repository = _repository()
    now = datetime.now(UTC)
    repository.enqueue(
        StartResearchRequest(question="Recover"),
        session_id="recovery-session",
        timeout=timedelta(minutes=10),
        now=now,
    )
    first = repository.claim("worker-1", lease=timedelta(seconds=10), now=now)
    assert first is not None
    assert (
        repository.claim("worker-2", lease=timedelta(seconds=10), now=now + timedelta(seconds=5))
        is None
    )
    recovered = repository.claim(
        "worker-2", lease=timedelta(seconds=10), now=now + timedelta(seconds=11)
    )
    assert recovered is not None
    assert recovered.id == first.id


def _repository() -> ResearchRunRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in TABLES:
        table.create(engine, checkfirst=True)
    return ResearchRunRepository(sessionmaker(bind=engine, expire_on_commit=False))


def _completed_state(session_id: str, run_id: uuid.UUID) -> AgentState:
    return {
        "session_id": session_id,
        "run_id": run_id,
        "question": "Question",
        "status": AgentRunStatus.COMPLETED,
        "final_answer": "Validated answer.",
        "draft_answer": "UNVALIDATED",
        "claims": (),
        "citations": (),
        "source_previews": (),
        "evidence": (),
        "errors": (),
        "branch_outcomes": (),
        "trajectory": (),
        "tool_calls_used": 0,
        "repair_attempts": 0,
    }  # type: ignore[typeddict-item]
