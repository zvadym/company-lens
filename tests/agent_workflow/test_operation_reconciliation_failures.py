from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *
from company_lens.agent.calculation_intents import (
    BranchOperationDecision,
    CalculationIntent,
    OperationReconciliation,
)
from company_lens.agent.schemas import NodeAttempt
from company_lens.agent.workflow import _reconcile_operations


class ReconciliationResponseProvider:
    def __init__(self, responses: Sequence[OperationReconciliation | AgentError | str]) -> None:
        self.responses = list(responses)
        self.purposes: list[ModelPurpose] = []
        self.model_calls: list[tuple[ModelPurpose, tuple[ModelMessage, ...]]] = []

    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        del output_type
        self.purposes.append(purpose)
        self.model_calls.append((purpose, tuple(messages)))
        response = self.responses.pop(0)
        if isinstance(response, AgentError):
            raise ModelProviderError(response)
        if isinstance(response, str):
            return StructuredModelResult[OutputT](
                model="fake-repair",
                response_id="reconciliation-refusal",
                refusal=response,
            )
        return StructuredModelResult[OutputT](
            model="fake-repair",
            response_id=f"reconciliation-{len(self.purposes)}",
            output=cast(OutputT, response),
        )

    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult:
        del messages, purpose
        raise AssertionError("Reconciliation must use structured output.")


def test_refusal_is_immediate_provider_response_infrastructure() -> None:
    provider = ReconciliationResponseProvider(("Cannot reconcile.",))

    update = _reconcile_operations(
        _state(),
        Runtime(context=ResearchAgentRuntime(provider, FakeResearchTools())),
    )

    assert update["status"] is AgentRunStatus.FAILED
    assert provider.purposes == [ModelPurpose.OPERATION_RECONCILIATION]
    error = cast(tuple[AgentError, ...], update["errors"])[0]
    assert error.category is AgentErrorCategory.PROVIDER_RESPONSE
    assert error.code == "operation_reconciliation_refusal"


def test_recoverable_provider_failure_uses_bounded_attempts() -> None:
    errors = tuple(
        AgentError(
            category=AgentErrorCategory.PROVIDER_TIMEOUT,
            severity=AgentErrorSeverity.RECOVERABLE,
            code="openai_timeout",
            message="OpenAI request timed out.",
        )
        for _ in range(3)
    )
    provider = ReconciliationResponseProvider(errors)

    update = _reconcile_operations(
        _state(max_retries=2),
        Runtime(context=ResearchAgentRuntime(provider, FakeResearchTools())),
    )

    assert update["status"] is AgentRunStatus.FAILED
    assert provider.purposes == [ModelPurpose.OPERATION_RECONCILIATION] * 3
    assert cast(tuple[AgentError, ...], update["errors"])[0].category is (
        AgentErrorCategory.PROVIDER_TIMEOUT
    )
    assert cast(tuple[NodeAttempt, ...], update["node_attempts"])[0].attempts == 3


def test_schema_valid_semantic_failure_is_observed_quality_failure() -> None:
    provider = ReconciliationResponseProvider(
        (
            OperationReconciliation(
                branch_operations=(
                    BranchOperationDecision(
                        branch_id="growth",
                        operation="quarter_over_quarter_growth",
                    ),
                    BranchOperationDecision(
                        branch_id="growth",
                        operation="quarter_over_quarter_growth",
                    ),
                )
            ),
        )
    )

    update = _reconcile_operations(
        _state(),
        Runtime(context=ResearchAgentRuntime(provider, FakeResearchTools())),
    )

    assert update["status"] is AgentRunStatus.FAILED
    error = cast(tuple[AgentError, ...], update["errors"])[0]
    assert error.category is AgentErrorCategory.VALIDATION
    assert error.code == "operation_reconciliation_failed"


def _state(*, max_retries: int = 0) -> AgentState:
    source = FinancialFactsBranch(
        branch_id="revenue",
        request=FinancialFactQuery(company_ids=(COMPANY_ID,), metrics=("revenue",)),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            source,
            CalculationBranch(
                branch_id="growth",
                operation="percentage_change",
                input_refs=(source.branch_id,),
                depends_on=(source.branch_id,),
            ),
        ),
    )
    state = create_initial_agent_state(
        "Show QoQ revenue growth.",
        session_id="operation-reconciliation-failure",
        policy=ExecutionPolicy(max_retries_per_node=max_retries),
    )
    state.update(
        {
            "analysis": QuestionAnalysis(
                normalized_question="Show QoQ revenue growth.",
                route=ResearchRoute.CALCULATION,
                required_capabilities=(
                    AgentCapability.FINANCIAL_FACTS,
                    AgentCapability.CALCULATIONS,
                ),
                calculation_intents=(
                    CalculationIntent(
                        operation="quarter_over_quarter_growth",
                        metrics=("revenue",),
                    ),
                ),
            ),
            "resolved_query": ResolvedQuery(
                query="Show QoQ revenue growth.",
                company_ids=(COMPANY_ID,),
                metrics=("revenue",),
            ),
            "execution_plan": plan,
        }
    )
    return state


__all__ = ("ReconciliationResponseProvider",)
