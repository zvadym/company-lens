from __future__ import annotations

import json
from decimal import Decimal

from company_lens.agent.calculation_intents import OperationReconciliation
from company_lens.agent.schemas import (
    AgentState,
    CalculationBranch,
    ExecutionBranch,
    ExecutionPlan,
    QuestionAnalysis,
    SessionMemory,
)
from company_lens.agent.workflow_operation_conflicts import (
    _branch_metrics,
    _effective_calculation_intents,
)


def _apply_operation_reconciliation(
    plan: ExecutionPlan,
    reconciliation: OperationReconciliation,
) -> ExecutionPlan:
    calculation_ids = tuple(
        branch.branch_id for branch in plan.branches if isinstance(branch, CalculationBranch)
    )
    decision_ids = tuple(decision.branch_id for decision in reconciliation.branch_operations)
    if len(decision_ids) != len(set(decision_ids)):
        raise ValueError("reconciliation decisions must be unique")
    if set(decision_ids) != set(calculation_ids) or len(decision_ids) != len(calculation_ids):
        raise ValueError("reconciliation decisions must exactly cover calculation branches")
    decisions = {decision.branch_id: decision for decision in reconciliation.branch_operations}
    branches: list[ExecutionBranch] = []
    for branch in plan.branches:
        if not isinstance(branch, CalculationBranch):
            branches.append(branch)
            continue
        decision = decisions[branch.branch_id]
        values = branch.model_dump()
        values.update(
            {
                "operation": decision.operation,
                "window": decision.window,
                "years": Decimal(str(decision.years)) if decision.years is not None else None,
                "base": branch.base if decision.base is None else Decimal(str(decision.base)),
            }
        )
        branches.append(CalculationBranch.model_validate(values))
    return plan.model_copy(update={"branches": tuple(branches)})


def _reconciliation_context(
    state: AgentState,
    analysis: QuestionAnalysis,
    plan: ExecutionPlan,
    memory: SessionMemory | None,
    reason_codes: tuple[str, ...],
) -> str:
    effective = _effective_calculation_intents(analysis, memory)
    calculations = tuple(
        branch for branch in plan.branches if isinstance(branch, CalculationBranch)
    )
    payload = {
        "question": state["question"],
        "effective_intents": [intent.model_dump(mode="json") for intent in effective],
        "conflict_reason_codes": list(reason_codes),
        "calculation_branches": [
            {
                "branch_id": branch.branch_id,
                "operation": branch.operation,
                "metrics": list(_branch_metrics(plan, branch)),
                "input_count": len(branch.input_refs),
                "window": branch.window,
                "years": str(branch.years) if branch.years is not None else None,
                "base": str(branch.base),
            }
            for branch in calculations
        ],
        "policy": {"max_retries_per_node": state["policy"].max_retries_per_node},
    }
    return json.dumps(payload, sort_keys=True)


def _plan_topology(plan: ExecutionPlan) -> tuple[dict[str, object], ...]:
    topology: list[dict[str, object]] = []
    for branch in plan.branches:
        values = branch.model_dump(mode="json")
        if isinstance(branch, CalculationBranch):
            for field in ("operation", "window", "years", "base"):
                values.pop(field, None)
        topology.append(values)
    return tuple(topology)


__all__ = (
    "_apply_operation_reconciliation",
    "_plan_topology",
    "_reconciliation_context",
)
