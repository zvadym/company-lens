from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from company_lens.agent.events import AgentExecutionEvent
from company_lens.agent.schemas import (
    AgentError,
    AgentErrorCategory,
    AgentErrorSeverity,
    AgentRunStatus,
    AgentState,
    ExecutionPolicy,
)
from company_lens.agent.workflow import create_initial_agent_state
from company_lens.evals.agent_runner import run_golden_agent_observations
from company_lens.evals.golden import load_golden_dataset

FOLLOW_UP = Path("evals/datasets/golden/follow_up.v1.yaml")


def test_provider_failure_in_an_intermediate_turn_is_infrastructure_error() -> None:
    class ProviderFailingAgent:
        calls = 0

        def run(
            self,
            question: str,
            *,
            session_id: str,
            policy: ExecutionPolicy,
            observer: Callable[[AgentExecutionEvent], None] | None = None,
        ) -> AgentState:
            self.calls += 1
            state = create_initial_agent_state(
                question,
                session_id=session_id,
                policy=policy,
            )
            state.update(
                {
                    "status": AgentRunStatus.ABSTAINED,
                    "errors": (
                        AgentError(
                            category=AgentErrorCategory.PROVIDER_SERVICE,
                            severity=AgentErrorSeverity.RECOVERABLE,
                            code="openai_service",
                            message="OpenAI service returned a transient error.",
                            node="resolve_entities",
                            attempt=3,
                        ),
                    ),
                }
            )
            return state

    agent = ProviderFailingAgent()
    observations = run_golden_agent_observations(
        load_golden_dataset(FOLLOW_UP),
        agent,
        policy=ExecutionPolicy(),
        case_ids=("followup_add_company_to_comparison_001",),
        run_token="provider-failure",
    )

    assert agent.calls == 1
    assert observations[0].outcome == "infrastructure_error"
    assert observations[0].failure_code == "provider_execution_failed"
    assert observations[0].operational is not None
