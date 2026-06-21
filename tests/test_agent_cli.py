from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from company_lens import cli
from company_lens.agent.persistence import (
    ResearchSessionError,
    ResearchSessionMetadata,
    ResearchSessionSnapshot,
    SessionErrorCode,
)
from company_lens.agent.schemas import (
    AgentCapability,
    AgentRunStatus,
    AgentState,
    CitationReference,
    EvidenceEnvelope,
    EvidenceKind,
    ExecutionPolicy,
    QuestionAnalysis,
    ResearchRoute,
    TrajectoryEvent,
    TrajectoryStatus,
)
from company_lens.agent.workflow import create_initial_agent_state
from company_lens.config import Settings


class FakeAgent:
    def __init__(self, state: AgentState) -> None:
        self.state = state
        self.run_call: tuple[str, str, ExecutionPolicy] | None = None
        self.resume_call: str | None = None

    def run(self, question: str, *, session_id: str, policy: ExecutionPolicy) -> AgentState:
        self.run_call = (question, session_id, policy)
        state = dict(self.state)
        state["session_id"] = session_id
        return state  # type: ignore[return-value]

    def resume(self, session_id: str) -> AgentState:
        self.resume_call = session_id
        return self.state


class FakeManager:
    def __init__(self, snapshot: ResearchSessionSnapshot | None = None) -> None:
        self.snapshot = snapshot
        self.cleared: str | None = None
        self.expiry_limit: int | None = None

    def inspect_session(self, session_id: str) -> ResearchSessionSnapshot | None:
        return self.snapshot

    def clear_session(self, session_id: str) -> bool:
        self.cleared = session_id
        return True

    def expire_sessions(self, *, limit: int) -> int:
        self.expiry_limit = limit
        return 3


def test_research_run_generates_session_and_outputs_enriched_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = _completed_state()
    agent = FakeAgent(state)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(OPENAI_API_KEY="test-key", _env_file=None),
    )
    monkeypatch.setattr(cli, "open_persistent_research_agent", _context_value(agent))

    exit_code = cli.main(
        [
            "research",
            "run",
            "What was revenue?",
            "--max-tool-calls",
            "7",
            "--include-trajectory",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert uuid.UUID(payload["session_id"])
    assert payload["status"] == "completed"
    assert payload["citations"][0]["source_urls"] == ["https://example.test/fact"]
    assert payload["execution"]["trajectory"][0]["node"] == "finalize_response"
    assert agent.run_call is not None
    assert agent.run_call[0] == "What was revenue?"
    assert agent.run_call[1] == payload["session_id"]
    assert agent.run_call[2].max_tool_calls == 7


def test_research_failed_state_returns_one_and_compact_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = _completed_state()
    state["status"] = AgentRunStatus.FAILED
    state["final_answer"] = None
    agent = FakeAgent(state)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(OPENAI_API_KEY="test-key", _env_file=None),
    )
    monkeypatch.setattr(cli, "open_persistent_research_agent", _context_value(agent))

    exit_code = cli.main(["research", "run", "Question", "--session-id", "known-session"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["session_id"] == "known-session"
    assert payload["execution"]["trajectory"] == []


@pytest.mark.parametrize("status", [AgentRunStatus.PARTIAL, AgentRunStatus.ABSTAINED])
def test_research_nonfailed_terminal_outcomes_return_zero(
    status: AgentRunStatus,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = _completed_state()
    state["status"] = status
    if status is AgentRunStatus.ABSTAINED:
        state["final_answer"] = None
    agent = FakeAgent(state)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(OPENAI_API_KEY="test-key", _env_file=None),
    )
    monkeypatch.setattr(cli, "open_persistent_research_agent", _context_value(agent))

    exit_code = cli.main(["research", "resume", "session-1"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == status.value
    assert agent.resume_call == "session-1"


def test_research_management_commands_do_not_build_openai_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = _completed_state()
    now = datetime.now(UTC)
    snapshot = ResearchSessionSnapshot(
        metadata=ResearchSessionMetadata(
            session_id="session-1",
            turn_count=1,
            last_run_id=state["run_id"],
            active_run_id=None,
            lease_expires_at=None,
            expires_at=now,
            last_accessed_at=now,
            created_at=now,
            updated_at=now,
        ),
        state=state,
        checkpoint_id="checkpoint-1",
        pending_nodes=(),
        resumable=False,
    )
    manager = FakeManager(snapshot)
    setup_calls: list[Settings] = []
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(cli, "open_research_session_manager", _context_value(manager))
    monkeypatch.setattr(cli, "setup_research_persistence", setup_calls.append)
    monkeypatch.setattr(
        cli,
        "open_persistent_research_agent",
        lambda _: pytest.fail("OpenAI runtime should not be built."),
    )

    assert cli.main(["research", "setup"]) == 0
    assert json.loads(capsys.readouterr().out)["operation"] == "setup"
    assert cli.main(["research", "inspect", "session-1"]) == 0
    assert json.loads(capsys.readouterr().out)["latest_run"]["answer"] == "Revenue was 10."
    assert cli.main(["research", "clear", "session-1", "--yes"]) == 0
    assert json.loads(capsys.readouterr().out)["deleted"] is True
    assert cli.main(["research", "expire", "--limit", "5"]) == 0
    assert json.loads(capsys.readouterr().out)["expired"] == 3
    assert setup_calls
    assert manager.cleared == "session-1"
    assert manager.expiry_limit == 5


def test_research_session_error_is_safe_json_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))

    @contextmanager
    def broken_manager(_: Settings) -> Any:
        raise ResearchSessionError(SessionErrorCode.BUSY, "Research session is busy.")
        yield

    monkeypatch.setattr(cli, "open_research_session_manager", broken_manager)

    exit_code = cli.main(["research", "inspect", "session-1"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {"code": "session_busy", "message": "Research session is busy."}
    }


def test_research_configuration_error_does_not_expose_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))

    @contextmanager
    def broken_agent(_: Settings) -> Any:
        raise ValueError("sensitive configuration value")
        yield

    monkeypatch.setattr(cli, "open_persistent_research_agent", broken_agent)

    exit_code = cli.main(["research", "run", "Question"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "sensitive" not in captured.err
    assert json.loads(captured.err)["error"]["code"] == "invalid_research_request"


def test_research_clear_requires_confirmation() -> None:
    with pytest.raises(SystemExit) as captured:
        cli.main(["research", "clear", "session-1"])
    assert captured.value.code == 2


def _completed_state() -> AgentState:
    state = create_initial_agent_state("What was revenue?", session_id="session-1")
    state.update(
        {
            "status": AgentRunStatus.COMPLETED,
            "analysis": QuestionAnalysis(
                normalized_question="What was revenue?",
                route=ResearchRoute.STRUCTURED_ONLY,
                required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
            ),
            "final_answer": "Revenue was 10.",
            "evidence": (
                EvidenceEnvelope(
                    evidence_id="financial_fact:1",
                    kind=EvidenceKind.FINANCIAL_FACT,
                    summary="Revenue was 10.",
                    source_urls=("https://example.test/fact",),
                    lineage_refs=("fact:1",),
                ),
            ),
            "citations": (CitationReference(evidence_id="financial_fact:1", label="Revenue fact"),),
            "trajectory": (
                TrajectoryEvent(
                    node="finalize_response",
                    status=TrajectoryStatus.COMPLETED,
                    occurred_at=datetime.now(UTC),
                    summary="Completed.",
                ),
            ),
        }
    )
    return state


def _context_value(value: object) -> Any:
    @contextmanager
    def context(_: Settings) -> Any:
        yield value

    return context
