from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from company_lens.agent.calculation_intents import (
    BranchOperationDecision,
    OperationReconciliation,
)
from company_lens.agent.schemas import (
    CalculationBranch,
    ChartBranch,
    ExecutionPlan,
    FinancialFactsBranch,
    ResearchRoute,
)
from company_lens.agent.workflow_operation_reconciliation import (
    _apply_operation_reconciliation,
)
from company_lens.financials.schemas import FinancialFactQuery


def test_application_changes_only_operation_and_applicable_scalars() -> None:
    plan = _plan("percentage_change")
    before = plan.model_dump(mode="json")

    reconciled = _apply_operation_reconciliation(
        plan,
        OperationReconciliation(
            branch_operations=(
                BranchOperationDecision(
                    branch_id="growth",
                    operation="quarter_over_quarter_growth",
                ),
            )
        ),
    )

    assert _calculation(reconciled).operation == "quarter_over_quarter_growth"
    after = reconciled.model_dump(mode="json")
    for key in ("branch_id", "kind", "depends_on", "optional", "input_refs"):
        assert after["branches"][1][key] == before["branches"][1][key]
    assert after["branches"][0] == before["branches"][0]
    assert after["branches"][2] == before["branches"][2]


@pytest.mark.parametrize(
    "decisions",
    [
        (),
        (
            BranchOperationDecision(
                branch_id="growth",
                operation="quarter_over_quarter_growth",
            ),
            BranchOperationDecision(
                branch_id="growth",
                operation="quarter_over_quarter_growth",
            ),
        ),
        (
            BranchOperationDecision(
                branch_id="unknown",
                operation="quarter_over_quarter_growth",
            ),
        ),
    ],
)
def test_application_rejects_missing_duplicate_or_unknown_decisions(
    decisions: tuple[BranchOperationDecision, ...],
) -> None:
    with pytest.raises(ValueError):
        _apply_operation_reconciliation(
            _plan("percentage_change"),
            OperationReconciliation(branch_operations=decisions),
        )


def test_application_rejects_operation_with_incompatible_input_arity() -> None:
    with pytest.raises(ValueError):
        _apply_operation_reconciliation(
            _plan("percentage_change"),
            OperationReconciliation(
                branch_operations=(BranchOperationDecision(branch_id="growth", operation="margin"),)
            ),
        )


def test_scalar_rules_clear_irrelevant_values_and_preserve_default_base() -> None:
    rolling = _plan("rolling_average", window=4)

    reconciled = _apply_operation_reconciliation(
        rolling,
        OperationReconciliation(
            branch_operations=(
                BranchOperationDecision(
                    branch_id="growth",
                    operation="normalised_index",
                    base=None,
                ),
            )
        ),
    )

    branch = _calculation(reconciled)
    assert branch.window is None
    assert branch.years is None
    assert branch.base == Decimal("100")


def test_decision_rejects_inapplicable_non_null_scalar() -> None:
    with pytest.raises(ValidationError):
        BranchOperationDecision(
            branch_id="growth",
            operation="percentage_change",
            window=8,
        )


def _plan(operation: str, *, window: int | None = None) -> ExecutionPlan:
    source = FinancialFactsBranch(
        branch_id="revenue",
        request=FinancialFactQuery(tickers=("NET",), metrics=("revenue",)),
    )
    calculation = CalculationBranch(
        branch_id="growth",
        operation=operation,
        input_refs=(source.branch_id,),
        depends_on=(source.branch_id,),
        window=window,
    )
    chart = ChartBranch(
        branch_id="chart",
        chart_type="line",
        dataset_ref=calculation.branch_id,
        depends_on=(calculation.branch_id,),
        title="Revenue growth",
    )
    return ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(source, calculation, chart),
    )


def _calculation(plan: ExecutionPlan) -> CalculationBranch:
    return next(branch for branch in plan.branches if isinstance(branch, CalculationBranch))
