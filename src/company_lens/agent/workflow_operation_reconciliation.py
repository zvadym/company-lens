from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *
from company_lens.agent.workflow_operation_conflicts import (
    _detect_operation_conflict,
    _effective_calculation_intents,
)
from company_lens.agent.workflow_operation_reconciliation_plan import (
    _apply_operation_reconciliation,
    _plan_topology,
    _reconciliation_context,
)
from company_lens.agent.workflow_operation_reconciliation_updates import (
    _provider_failure_update,
    _semantic_failure_update,
    _trajectory_details,
)
from company_lens.agent.workflow_operation_telemetry import record_operation_reconciliation

_NODE = "reconcile_operations"


def _reconcile_operations(
    state: AgentState,
    runtime: Runtime[ResearchAgentRuntime],
) -> dict[str, object]:
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped(_NODE)
    started = time.monotonic()
    analysis = state.get("analysis")
    resolved = state.get("resolved_query")
    plan = state.get("execution_plan")
    if analysis is None or resolved is None or plan is None:
        error = _validation_error(_NODE, "missing_reconciliation_inputs")
        return _semantic_failure_update(error, started, (), attempts=0)

    memory = state.get("session_memory")
    effective = _effective_calculation_intents(analysis, memory)
    intent_operations = tuple(intent.operation for intent in effective)
    planned_operations = _calculation_operations(plan)
    conflict = _detect_operation_conflict(analysis, plan, memory)
    if not conflict.required:
        record_operation_reconciliation(
            required=False,
            intent_operations=intent_operations,
            conflict_reasons=(),
            branch_count=len(planned_operations),
            decision_count=0,
            final_operations=planned_operations,
            attempts=0,
            outcome="not_required",
        )
        return {
            "trajectory": (
                _event(
                    _NODE,
                    TrajectoryStatus.SKIPPED,
                    "Calculation operations already match typed intent.",
                    started,
                    details={
                        "required": False,
                        "conflict_count": 0,
                        "outcome": "not_required",
                    },
                ),
            )
        }

    messages = (
        _system_prompt_message(runtime, "agent/reconcile-operations"),
        ModelMessage(
            role="user",
            content=_reconciliation_context(state, analysis, plan, memory, conflict.reason_codes),
        ),
    )
    output, attempts, error = _generate_structured_with_retries(
        runtime.context.model_provider,
        messages,
        OperationReconciliation,
        purpose=ModelPurpose.OPERATION_RECONCILIATION,
        max_retries=state["policy"].max_retries_per_node,
        node=_NODE,
    )
    if error is not None:
        if error.category is AgentErrorCategory.PROVIDER_REFUSAL:
            error = error.model_copy(
                update={
                    "category": AgentErrorCategory.PROVIDER_RESPONSE,
                    "code": "operation_reconciliation_refusal",
                    "message": (
                        "The operation reconciliation model declined the structured request."
                    ),
                }
            )
        record_operation_reconciliation(
            required=True,
            intent_operations=intent_operations,
            conflict_reasons=conflict.reason_codes,
            branch_count=len(planned_operations),
            decision_count=0,
            final_operations=planned_operations,
            attempts=attempts,
            outcome="provider_failure",
        )
        return _provider_failure_update(error, started, conflict.reason_codes, attempts)

    assert output is not None
    try:
        reconciled = _apply_operation_reconciliation(plan, output)
        if _plan_topology(reconciled) != _plan_topology(plan):
            raise ValueError("operation reconciliation changed plan topology")
        remaining = _detect_operation_conflict(analysis, reconciled, memory)
        if remaining.required:
            raise ValueError("operation reconciliation left a typed conflict")
        reconciled = _normalize_and_validate_plan(
            reconciled,
            analysis,
            resolved,
            state["policy"],
            retrieval_index_name=runtime.context.retrieval_index_name,
            retrieval_index_version=runtime.context.retrieval_index_version,
        )
        if _plan_topology(reconciled) != _plan_topology(plan):
            raise ValueError("plan validation changed reconciled topology")
    except (TypeError, ValueError):
        semantic_error = _agent_error(
            _NODE,
            "operation_reconciliation_failed",
            "Operation reconciliation could not produce a compatible validated plan.",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        record_operation_reconciliation(
            required=True,
            intent_operations=intent_operations,
            conflict_reasons=conflict.reason_codes,
            branch_count=len(planned_operations),
            decision_count=len(output.branch_operations),
            final_operations=planned_operations,
            attempts=attempts,
            outcome="semantic_failure",
        )
        return _semantic_failure_update(
            semantic_error,
            started,
            conflict.reason_codes,
            attempts=attempts,
        )

    final_operations = _calculation_operations(reconciled)
    record_operation_reconciliation(
        required=True,
        intent_operations=intent_operations,
        conflict_reasons=conflict.reason_codes,
        branch_count=len(planned_operations),
        decision_count=len(output.branch_operations),
        final_operations=final_operations,
        attempts=attempts,
        outcome="completed",
    )
    return {
        "execution_plan": reconciled,
        "node_attempts": (NodeAttempt(node=_NODE, attempts=attempts),),
        "trajectory": (
            _event(
                _NODE,
                TrajectoryStatus.COMPLETED,
                "Calculation operations were reconciled and validated.",
                started,
                details=_trajectory_details(
                    conflict.reason_codes,
                    attempts=attempts,
                    outcome="completed",
                    decision_count=len(output.branch_operations),
                ),
            ),
        ),
    }


def _calculation_operations(plan: ExecutionPlan) -> tuple[str, ...]:
    return tuple(
        branch.operation for branch in plan.branches if isinstance(branch, CalculationBranch)
    )


__all__ = ("_apply_operation_reconciliation", "_reconcile_operations")
