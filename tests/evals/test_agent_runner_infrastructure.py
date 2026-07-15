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


def test_persistent_provider_failure_is_infrastructure_error_after_one_case_retry() -> None:
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

    assert agent.calls == 2
    assert observations[0].outcome == "infrastructure_error"
    assert observations[0].failure_code == "provider_execution_failed"
    assert observations[0].operational is not None
    assert observations[0].operational.retry_count == 1


def test_transient_provider_failure_replays_the_whole_conversation_in_a_new_session() -> None:
    class TransientProviderFailingAgent:
        def __init__(self) -> None:
            self.calls = 0
            self.session_ids: list[str] = []

        def run(
            self,
            question: str,
            *,
            session_id: str,
            policy: ExecutionPolicy,
            observer: Callable[[AgentExecutionEvent], None] | None = None,
        ) -> AgentState:
            self.calls += 1
            self.session_ids.append(session_id)
            state = create_initial_agent_state(
                question,
                session_id=session_id,
                policy=policy,
            )
            if self.calls == 1:
                state.update(
                    {
                        "status": AgentRunStatus.ABSTAINED,
                        "errors": (
                            AgentError(
                                category=AgentErrorCategory.PROVIDER_TIMEOUT,
                                severity=AgentErrorSeverity.RECOVERABLE,
                                code="openai_timeout",
                                message="OpenAI request timed out.",
                                node="generate_answer",
                                attempt=3,
                            ),
                        ),
                    }
                )
            else:
                state["status"] = AgentRunStatus.COMPLETED
            return state

    agent = TransientProviderFailingAgent()
    observations = run_golden_agent_observations(
        load_golden_dataset(FOLLOW_UP),
        agent,
        policy=ExecutionPolicy(),
        case_ids=("followup_add_company_to_comparison_001",),
        run_token="transient-provider-failure",
    )

    assert agent.calls == 3
    assert agent.session_ids[0] != agent.session_ids[1]
    assert agent.session_ids[1] == agent.session_ids[2]
    assert agent.session_ids[1].endswith("-retry-1")
    assert observations[0].outcome == "observed"
    assert observations[0].operational is not None
    assert observations[0].operational.retry_count == 1
