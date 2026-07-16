from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from company_lens.agent.schemas import (
    AgentCapability,
    AgentError,
    AgentErrorCategory,
    AgentErrorSeverity,
    AgentRunStatus,
    CompanyTarget,
    ExecutionPlan,
    FinancialFactsBranch,
    QuestionAnalysis,
    ResearchFrame,
    ResearchRoute,
)
from company_lens.agent.workflow import create_initial_agent_state
from company_lens.config import Settings
from company_lens.evals.orchestrator import EvaluationRequest, run_evaluation
from company_lens.financials.schemas import FinancialFactQuery
from company_lens.retrieval.adaptive_schemas import ResolvedQuery
from tests.evals.fakes_langfuse import FakeLangfuse

CORE = Path("evals/datasets/golden/core.v1.yaml")
GATE = Path("evals/gates/eval-fast.v1.yaml")
SCORES = Path("evals/score-contracts/foundation.v1.yaml")


class TerminalReconciliationAgent:
    def __init__(self, *, infrastructure: bool) -> None:
        self.infrastructure = infrastructure
        self.calls = 0

    def run(self, question: str, *, session_id: str, policy: object, observer: object = None):
        del policy, observer
        self.calls += 1
        state = create_initial_agent_state(question, session_id=session_id)
        resolved = ResolvedQuery(query=question, metrics=("revenue",))
        analysis = QuestionAnalysis(
            normalized_question=question,
            route=ResearchRoute.STRUCTURED_ONLY,
            required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
        )
        plan = ExecutionPlan(
            route=ResearchRoute.STRUCTURED_ONLY,
            branches=(
                FinancialFactsBranch(
                    branch_id="facts",
                    request=FinancialFactQuery(tickers=("NET",), metrics=("revenue",)),
                ),
            ),
        )
        state.update(
            {
                "status": AgentRunStatus.FAILED,
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
                "errors": (
                    AgentError(
                        category=(
                            AgentErrorCategory.PROVIDER_RESPONSE
                            if self.infrastructure
                            else AgentErrorCategory.VALIDATION
                        ),
                        severity=AgentErrorSeverity.TERMINAL,
                        code=(
                            "operation_reconciliation_refusal"
                            if self.infrastructure
                            else "operation_reconciliation_failed"
                        ),
                        message="Operation reconciliation could not produce a safe plan.",
                        node="reconcile_operations",
                    ),
                ),
            }
        )
        return state


def test_provider_reconciliation_failure_is_not_evaluated_infrastructure(
    tmp_path: Path,
) -> None:
    agent = TerminalReconciliationAgent(infrastructure=True)

    outcome = run_evaluation(
        _request(tmp_path),
        settings=_settings(),
        client=FakeLangfuse(),
        agent_provider=_agent_provider(agent),
    )

    assert outcome.exit_code == 2
    assert outcome.execution.gate_status == "not_evaluated"
    assert agent.calls == 2


def test_semantic_reconciliation_failure_is_an_observed_quality_failure(
    tmp_path: Path,
) -> None:
    agent = TerminalReconciliationAgent(infrastructure=False)

    outcome = run_evaluation(
        _request(tmp_path),
        settings=_settings(),
        client=FakeLangfuse(),
        agent_provider=_agent_provider(agent),
    )

    assert outcome.exit_code == 1
    assert outcome.execution.gate_status == "failed"
    assert agent.calls == 1


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


def _agent_provider(agent: TerminalReconciliationAgent):
    @contextmanager
    def provider() -> Iterator[TerminalReconciliationAgent]:
        yield agent

    return provider
