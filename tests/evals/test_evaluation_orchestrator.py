from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from company_lens.agent.schemas import (
    AgentCapability,
    AgentRunStatus,
    AnswerValidation,
    CompanyTarget,
    ExecutionPlan,
    FinancialFactsBranch,
    QuestionAnalysis,
    ResearchFrame,
    ResearchRoute,
)
from company_lens.agent.workflow import create_initial_agent_state
from company_lens.config import Settings
from company_lens.evals.models import EvaluationRecoveryJournal
from company_lens.evals.orchestrator import EvaluationRequest, run_evaluation
from company_lens.evals.replay import replay_evaluation
from company_lens.evals.reporting import (
    initialize_evaluation_journal,
    load_evaluation_journal,
    recover_evaluation_artifacts,
)
from company_lens.financials.schemas import FinancialFactQuery
from company_lens.retrieval.adaptive_schemas import ResolvedQuery
from tests.evals.fakes_langfuse import FakeLangfuse

CORE = Path("evals/datasets/golden/core.v1.yaml")
GATE = Path("evals/gates/eval-fast.v1.yaml")
SCORES = Path("evals/score-contracts/foundation.v1.yaml")


class PassingAgent:
    def __init__(self, client: FakeLangfuse) -> None:
        self.client = client
        self.calls = 0

    def run(self, question: str, *, session_id: str, policy: object, observer: object = None):
        self.calls += 1
        assert self.client.counters.item_writes > 0
        plan = ExecutionPlan(
            route=ResearchRoute.STRUCTURED_ONLY,
            branches=(
                FinancialFactsBranch(
                    branch_id="facts",
                    request=FinancialFactQuery(tickers=("NET",), metrics=("revenue",)),
                ),
            ),
        )
        resolved = ResolvedQuery(query=question, metrics=("revenue",))
        analysis = QuestionAnalysis(
            normalized_question=question,
            route=ResearchRoute.STRUCTURED_ONLY,
            required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
        )
        state = create_initial_agent_state(question, session_id=session_id)
        state.update(
            {
                "status": AgentRunStatus.COMPLETED,
                "resolved_query": resolved,
                "research_frame": ResearchFrame(
                    question=question,
                    analysis=analysis,
                    resolved_query=resolved,
                    company_targets=(
                        CompanyTarget(
                            mention="Cloudflare",
                            ticker="NET",
                            status="resolved",
                            source="current_question",
                        ),
                    ),
                ),
                "execution_plan": plan,
                "final_answer": "Revenue was reported [evidence-1].",
                "answer_validation": AnswerValidation(
                    valid=True,
                    cited_evidence_ids=("evidence-1",),
                ),
            }
        )
        return state


def test_orchestrator_preflights_then_materializes_trusted_execution(tmp_path: Path) -> None:
    client = FakeLangfuse()
    agent = PassingAgent(client)
    outcome = run_evaluation(
        _request(tmp_path),
        settings=_settings(),
        client=client,
        agent_provider=_agent_provider(agent),
    )

    assert outcome.exit_code == 0
    assert outcome.execution.status == "completed"
    assert outcome.execution.gate_status == "passed"
    assert outcome.journal.phase == "terminal"
    assert outcome.journal.sequence >= 4
    assert agent.calls == 1
    assert (tmp_path / "evaluation-execution.json").exists()
    assert (tmp_path / "evaluation-summary.md").exists()
    assert load_evaluation_journal(tmp_path / "evaluation-journal.json") == outcome.journal


def test_wrong_project_fails_before_remote_writes_and_agent_calls(tmp_path: Path) -> None:
    client = FakeLangfuse(project_id="wrong-project")
    agent = PassingAgent(client)
    outcome = run_evaluation(
        _request(tmp_path),
        settings=_settings(),
        client=client,
        agent_provider=_agent_provider(agent),
    )

    assert outcome.exit_code == 2
    assert outcome.execution.status == "errored"
    assert outcome.execution.gate_status == "not_evaluated"
    assert client.counters.dataset_writes == 0
    assert client.counters.item_writes == 0
    assert agent.calls == 0
    assert outcome.journal.phase == "terminal"
    assert outcome.journal.reporting_status == "not_requested"


def test_manifest_replay_reads_recorded_snapshot_without_sync_mutations(tmp_path: Path) -> None:
    client = FakeLangfuse()
    first = run_evaluation(
        _request(tmp_path / "source"),
        settings=_settings(),
        client=client,
        agent_provider=_agent_provider(PassingAgent(client)),
    )
    writes_before = (
        client.counters.dataset_writes,
        client.counters.item_writes,
        client.counters.score_config_writes,
    )

    replay = replay_evaluation(
        tmp_path / "source" / "evaluation-execution.json",
        output_dir=tmp_path / "replay",
        execution_id=uuid4(),
        settings=_settings(),
        client=client,
        agent_provider=_agent_provider(PassingAgent(client)),
    )

    assert first.exit_code == replay.exit_code == 0
    assert replay.execution.manifest.replay_of_execution_id == first.execution.execution_id
    assert replay.execution.manifest.source_manifest_fingerprint == (
        first.execution.manifest.manifest_fingerprint
    )
    assert (
        client.counters.dataset_writes,
        client.counters.item_writes,
        client.counters.score_config_writes,
    ) == writes_before


def test_recovery_materializes_interrupted_journal_without_remote_calls(tmp_path: Path) -> None:
    client = FakeLangfuse()
    source = run_evaluation(
        _request(tmp_path / "source"),
        settings=_settings(),
        client=client,
        agent_provider=_agent_provider(PassingAgent(client)),
    )
    recovery_dir = tmp_path / "recovery"
    journal_path = recovery_dir / "evaluation-journal.json"
    interrupted = EvaluationRecoveryJournal(
        execution_id=source.execution.execution_id,
        sequence=0,
        updated_at=datetime.now(UTC),
        project_identity=source.execution.manifest.project_identity,
        manifest=source.execution.manifest,
        phase="running",
        status="running",
        gate_status="pending",
        reporting_status="not_requested",
    )
    initialize_evaluation_journal(journal_path, interrupted)
    counters_before = vars(client.counters).copy()

    journal, execution = recover_evaluation_artifacts(journal_path, recovery_dir)

    assert journal.phase == "terminal"
    assert execution.status == "errored"
    assert execution.gate_status == "not_evaluated"
    assert "evaluation_interrupted" in execution.failure_codes
    assert vars(client.counters) == counters_before


def _request(output_dir: Path) -> EvaluationRequest:
    return EvaluationRequest(
        dataset_paths=(CORE,),
        gate_path=GATE,
        score_contract_path=SCORES,
        output_dir=output_dir,
        max_cases=1,
        commit_sha="abcdef1",
    )


def _settings() -> Settings:
    return Settings(langfuse_project_id="project-testing", _env_file=None)


def _agent_provider(agent: PassingAgent):
    @contextmanager
    def provider() -> Iterator[PassingAgent]:
        yield agent

    return provider
