from __future__ import annotations

import socket
import threading
import time
import uuid
from collections.abc import Callable
from datetime import timedelta

from company_lens.agent.events import AgentExecutionEvent
from company_lens.agent.output import research_run_output
from company_lens.agent.persistence import (
    InterruptionReason,
    PersistentResearchAgent,
    ResearchRunInterrupted,
)
from company_lens.agent.schemas import AgentRunStatus, AgentState, ExecutionPolicy
from company_lens.db.models import ResearchRun
from company_lens.observability.context import bind_context
from company_lens.observability.telemetry import observe_operation
from company_lens.research.repository import ResearchRunRepository
from company_lens.research.schemas import ResearchResult, ResearchRunStatus


class ResearchWorker:
    def __init__(
        self,
        *,
        repository: ResearchRunRepository,
        agent: PersistentResearchAgent,
        worker_id: str | None = None,
        lease: timedelta = timedelta(seconds=60),
    ) -> None:
        self._repository = repository
        self._agent = agent
        self._worker_id = worker_id or f"{socket.gethostname()}:{uuid.uuid4()}"
        self._lease = lease

    def run_once(self) -> bool:
        run = self._repository.claim(self._worker_id, lease=self._lease)
        if run is None:
            return False
        with (
            bind_context(
                correlation_id=run.correlation_id,
                run_id=run.id,
                session_id=run.session_id,
            ),
            observe_operation(
                "research.run",
                kind="workflow",
                attributes={"research.session_id": run.session_id},
            ),
        ):
            return self._run_claimed(run)

    def _run_claimed(self, run: ResearchRun) -> bool:
        initial_reason = self._repository.interruption_reason(run.id)
        if initial_reason is not None:
            self._repository.finalize(
                run.id,
                _interruption_status(initial_reason),
                error_code=f"research_{initial_reason}",
                error_message=_interruption_message(initial_reason),
            )
            return True

        def observe(event: AgentExecutionEvent) -> None:
            self._repository.append_event(
                run.id,
                event.event_type,
                event.data,
                event_key=f"agent:v2:{event.event_key}",
            )
            self._repository.heartbeat(run.id, self._worker_id, lease=self._lease)

        try:
            with _LeaseHeartbeat(
                self._repository,
                run.id,
                self._worker_id,
                lease=self._lease,
            ):
                state = self._execute_run(
                    run.id, run.session_id, run.question, run.policy_json, observe
                )
        except ResearchRunInterrupted as exc:
            self._repository.finalize(
                run.id,
                _interruption_status(exc.reason),
                error_code=f"research_{exc.reason}",
                error_message=_interruption_message(exc.reason),
            )
            return True
        except Exception:
            self._repository.finalize(
                run.id,
                ResearchRunStatus.FAILED,
                error_code="research_execution_failed",
                error_message="The research run could not be completed.",
            )
            return True

        final_reason = self._repository.interruption_reason(run.id)
        if final_reason is not None:
            self._repository.finalize(
                run.id,
                _interruption_status(final_reason),
                error_code=f"research_{final_reason}",
                error_message=_interruption_message(final_reason),
            )
            return True

        output = research_run_output(state)
        result = ResearchResult(
            agent_status=output.status,
            answer=output.answer,
            citations=output.citations,
            chart=output.chart,
            warnings=tuple(error for error in output.execution.errors if error.recoverable),
            execution=output.execution,
            sources=output.sources,
        )
        self._repository.finalize(run.id, _public_status(output.status), result=result)
        return True

    def run_forever(self, *, poll_seconds: float) -> None:
        while True:
            if not self.run_once():
                time.sleep(poll_seconds)

    def _execute_run(
        self,
        run_id: uuid.UUID,
        session_id: str,
        question: str,
        policy_json: dict[str, object],
        observer: Callable[[AgentExecutionEvent], None],
    ) -> AgentState:
        snapshot = self._agent.inspect_session(session_id)

        def control() -> InterruptionReason | None:
            return self._repository.interruption_reason(run_id)

        if snapshot is not None and snapshot.state.get("run_id") == run_id:
            if snapshot.pending_nodes:
                return self._agent.resume(
                    session_id,
                    observer=observer,
                    control=control,
                    allow_run_takeover=True,
                )
            if snapshot.state.get("status") in {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.PARTIAL,
                AgentRunStatus.ABSTAINED,
                AgentRunStatus.FAILED,
            }:
                return snapshot.state
        if snapshot is not None and snapshot.pending_nodes:
            raise RuntimeError("Research session contains a different unfinished run.")
        return self._agent.run(
            question,
            session_id=session_id,
            policy=ExecutionPolicy.model_validate(policy_json),
            run_id=run_id,
            observer=observer,
            control=control,
            allow_run_takeover=True,
        )


class _LeaseHeartbeat:
    def __init__(
        self,
        repository: ResearchRunRepository,
        run_id: uuid.UUID,
        worker_id: str,
        *,
        lease: timedelta,
    ) -> None:
        self._repository = repository
        self._run_id = run_id
        self._worker_id = worker_id
        self._lease = lease
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> _LeaseHeartbeat:
        interval = max(0.05, min(10.0, self._lease.total_seconds() / 3))
        self._thread = threading.Thread(
            target=self._run,
            args=(interval,),
            name=f"research-heartbeat-{self._run_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _run(self, interval: float) -> None:
        while not self._stop.wait(interval):
            try:
                self._repository.heartbeat(
                    self._run_id,
                    self._worker_id,
                    lease=self._lease,
                )
            except Exception:
                # Execution still checks ownership and interruption at graph boundaries. A
                # transient heartbeat failure must not terminate this daemon thread noisily.
                continue


def _public_status(status: AgentRunStatus) -> ResearchRunStatus:
    return {
        AgentRunStatus.COMPLETED: ResearchRunStatus.COMPLETED,
        AgentRunStatus.PARTIAL: ResearchRunStatus.PARTIAL,
        AgentRunStatus.ABSTAINED: ResearchRunStatus.ABSTAINED,
        AgentRunStatus.FAILED: ResearchRunStatus.FAILED,
        AgentRunStatus.PENDING: ResearchRunStatus.FAILED,
        AgentRunStatus.RUNNING: ResearchRunStatus.FAILED,
    }[status]


def _interruption_status(reason: str) -> ResearchRunStatus:
    return ResearchRunStatus.CANCELLED if reason == "cancelled" else ResearchRunStatus.TIMED_OUT


def _interruption_message(reason: str) -> str:
    return (
        "Research run was cancelled."
        if reason == "cancelled"
        else "Research run exceeded its execution deadline."
    )
