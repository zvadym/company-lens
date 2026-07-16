from __future__ import annotations

import uuid

from company_lens.agent.calculation_intents import CalculationIntent
from company_lens.agent.schemas import (
    CalculationBranch,
    ExecutionPlan,
    FinancialFactsBranch,
    QuestionAnalysis,
    ResearchRoute,
    SessionMemory,
)
from company_lens.agent.workflow_operation_conflicts import (
    _detect_operation_conflict,
    _effective_calculation_intents,
)
from company_lens.financials.schemas import FinancialFactQuery


def test_consistent_typed_intent_requires_no_reconciliation() -> None:
    analysis = _analysis(_intent("quarter_over_quarter_growth"))
    plan = _plan("quarter_over_quarter_growth")

    conflict = _detect_operation_conflict(analysis, plan, SessionMemory())

    assert conflict.required is False
    assert conflict.reason_codes == ()
    assert conflict.branch_ids == ()


def test_operation_metric_and_missing_intent_conflicts_are_typed() -> None:
    operation = _detect_operation_conflict(
        _analysis(_intent("quarter_over_quarter_growth")),
        _plan("percentage_change"),
        SessionMemory(),
    )
    metric = _detect_operation_conflict(
        _analysis(_intent("quarter_over_quarter_growth", metrics=("net_income",))),
        _plan("quarter_over_quarter_growth"),
        SessionMemory(),
    )
    missing = _detect_operation_conflict(
        _analysis(),
        _plan("quarter_over_quarter_growth"),
        SessionMemory(),
    )

    assert operation.reason_codes == ("operation",)
    assert metric.reason_codes == ("metrics",)
    assert missing.reason_codes == ("missing",)


def test_one_intent_can_cover_multiple_company_branches() -> None:
    first = _source("net_revenue", uuid.UUID(int=1))
    second = _source("ddog_revenue", uuid.UUID(int=2))
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            first,
            second,
            _calculation("net_growth", first.branch_id, "quarter_over_quarter_growth"),
            _calculation("ddog_growth", second.branch_id, "quarter_over_quarter_growth"),
        ),
    )

    conflict = _detect_operation_conflict(
        _analysis(_intent("quarter_over_quarter_growth")),
        plan,
        SessionMemory(),
    )

    assert conflict.required is False


def test_equivalent_company_qualified_intents_cover_matching_company_branches() -> None:
    first = _source("net_revenue", uuid.UUID(int=1))
    second = _source("ddog_revenue", uuid.UUID(int=2))
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            first,
            second,
            _calculation("net_growth", first.branch_id, "quarter_over_quarter_growth"),
            _calculation("ddog_growth", second.branch_id, "quarter_over_quarter_growth"),
        ),
    )
    analysis = _analysis(
        _intent("quarter_over_quarter_growth", metrics=("cloudflare revenue",)),
        _intent("quarter_over_quarter_growth", metrics=("datadog revenue",)),
    )

    conflict = _detect_operation_conflict(analysis, plan, SessionMemory())

    assert conflict.required is False


def test_company_qualified_intents_still_surface_operation_disagreement() -> None:
    analysis = _analysis(
        _intent("quarter_over_quarter_growth", metrics=("cloudflare revenue",)),
        _intent("percentage_change", metrics=("datadog revenue",)),
    )

    conflict = _detect_operation_conflict(
        analysis,
        _plan("quarter_over_quarter_growth"),
        SessionMemory(),
    )

    assert conflict.reason_codes == ("ambiguous",)


def test_explicit_current_intent_wins_over_requested_inheritance() -> None:
    previous = _plan("year_over_year_growth")
    analysis = _analysis(
        _intent("quarter_over_quarter_growth"),
        inherit=True,
    )

    effective = _effective_calculation_intents(
        analysis,
        SessionMemory(last_execution_plan=previous),
    )

    assert tuple(item.operation for item in effective) == ("quarter_over_quarter_growth",)
    assert tuple(item.source for item in effective) == ("current",)


def test_inheritance_uses_the_previous_final_plan() -> None:
    previous = _plan("quarter_over_quarter_growth")
    analysis = _analysis(inherit=True)

    effective = _effective_calculation_intents(
        analysis,
        SessionMemory(last_execution_plan=previous),
    )
    conflict = _detect_operation_conflict(
        analysis,
        _plan("percentage_change"),
        SessionMemory(last_execution_plan=previous),
    )

    assert tuple(item.operation for item in effective) == ("quarter_over_quarter_growth",)
    assert tuple(item.source for item in effective) == ("inherited",)
    assert conflict.reason_codes == ("operation",)


def test_multiple_matching_intents_are_ambiguous() -> None:
    analysis = _analysis(
        _intent("quarter_over_quarter_growth"),
        _intent("percentage_change"),
    )

    conflict = _detect_operation_conflict(
        analysis,
        _plan("quarter_over_quarter_growth"),
        SessionMemory(),
    )

    assert conflict.reason_codes == ("ambiguous",)


def _intent(
    operation: str,
    *,
    metrics: tuple[str, ...] = ("revenue",),
) -> CalculationIntent:
    return CalculationIntent(operation=operation, metrics=metrics)


def _analysis(
    *intents: CalculationIntent,
    inherit: bool = False,
) -> QuestionAnalysis:
    return QuestionAnalysis(
        normalized_question="typed question",
        route=ResearchRoute.CALCULATION,
        calculation_intents=intents,
        inherit_previous_calculation_intents=inherit,
    )


def _source(branch_id: str, company_id: uuid.UUID) -> FinancialFactsBranch:
    return FinancialFactsBranch(
        branch_id=branch_id,
        request=FinancialFactQuery(company_ids=(company_id,), metrics=("revenue",)),
    )


def _calculation(branch_id: str, source_id: str, operation: str) -> CalculationBranch:
    return CalculationBranch(
        branch_id=branch_id,
        operation=operation,
        input_refs=(source_id,),
        depends_on=(source_id,),
    )


def _plan(operation: str) -> ExecutionPlan:
    source = _source("revenue", uuid.UUID(int=1))
    return ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(source, _calculation("growth", source.branch_id, operation)),
    )
