from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _normalize_default_chart_window(
    plan: ExecutionPlan,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
) -> ExecutionPlan:
    if not analysis.chart_requested or resolved.dates:
        return plan
    chart = next((item for item in plan.branches if isinstance(item, ChartBranch)), None)
    if chart is None:
        return plan
    plotted_refs = set(_chart_references(chart)) | set(_default_chart_references(plan))
    growth_calculations = {
        branch.branch_id: branch
        for branch in plan.branches
        if isinstance(branch, CalculationBranch)
        and branch.branch_id in plotted_refs
        and branch.operation
        in {"quarter_over_quarter_growth", "year_over_year_growth", "percentage_change"}
    }
    if not growth_calculations:
        return plan
    financial_refs = {
        reference
        for calculation in growth_calculations.values()
        for reference in calculation.input_refs
    }
    macro_refs = {
        branch.branch_id
        for branch in plan.branches
        if isinstance(branch, MacroSeriesBranch) and branch.branch_id in plotted_refs
    }
    use_quarterly_default = not _explicit_annual_growth_requested(analysis.normalized_question)
    force_yoy = use_quarterly_default and not _explicit_quarter_growth_requested(
        analysis.normalized_question
    )
    normalized: list[ExecutionBranch] = []
    applied_default_window = False
    for branch in plan.branches:
        if isinstance(branch, CalculationBranch) and branch.branch_id in growth_calculations:
            if force_yoy and branch.operation != "year_over_year_growth":
                branch = branch.model_copy(update={"operation": "year_over_year_growth"})
                applied_default_window = True
        elif isinstance(branch, FinancialFactsBranch) and branch.branch_id in financial_refs:
            if (
                use_quarterly_default
                and branch.request.period_start is None
                and branch.request.period_end is None
                and not branch.request.fiscal_years
                and not branch.request.fiscal_periods
            ):
                financial_request = branch.request.model_copy(
                    update={
                        "period_types": ("quarter",),
                        "limit": max(branch.request.limit, DEFAULT_CHART_QUARTERLY_FACT_LIMIT),
                    }
                )
                branch = branch.model_copy(update={"request": financial_request})
                applied_default_window = True
        elif (
            isinstance(branch, MacroSeriesBranch)
            and branch.branch_id in macro_refs
            and branch.request.observation_start is None
            and branch.request.observation_end is None
        ):
            macro_request = branch.request.model_copy(
                update={"limit": DEFAULT_CHART_MACRO_MONTH_LIMIT}
            )
            branch = branch.model_copy(update={"request": macro_request})
            applied_default_window = True
        normalized.append(branch)
    updates: dict[str, object] = {"branches": tuple(normalized)}
    if applied_default_window:
        updates["reason_codes"] = tuple(
            dict.fromkeys((*plan.reason_codes, DEFAULT_CHART_WINDOW_REASON))
        )
    return plan.model_copy(update=updates)


def _explicit_quarter_growth_requested(question: str) -> bool:
    normalized = question.casefold()
    return any(
        token in normalized for token in ("quarter-over-quarter", "quarter over quarter", "qoq")
    )


def _explicit_annual_growth_requested(question: str) -> bool:
    normalized = question.casefold()
    return any(token in normalized for token in ("annual", "yearly", "fiscal year"))


def _normalize_chart_branch(plan: ExecutionPlan) -> ChartBranch | None:
    chart = next((item for item in plan.branches if isinstance(item, ChartBranch)), None)
    if chart is None:
        return None
    plotted_refs = _default_chart_references(plan)
    current_refs = _chart_references(chart)
    if len(plotted_refs) <= 1 or set(plotted_refs).issubset(current_refs):
        return chart
    if not set(current_refs).issubset(plotted_refs):
        return chart
    ordered_refs = tuple(dict.fromkeys((*current_refs, *plotted_refs)))
    return chart.model_copy(
        update={
            "dataset_ref": ordered_refs[0],
            "depends_on": ordered_refs,
        }
    )


def _default_chart_references(plan: ExecutionPlan) -> tuple[str, ...]:
    calculation_inputs = {
        reference
        for branch in plan.branches
        if isinstance(branch, CalculationBranch)
        for reference in branch.input_refs
    }
    refs = [branch.branch_id for branch in plan.branches if isinstance(branch, CalculationBranch)]
    for branch in plan.branches:
        if (
            isinstance(branch, (FinancialFactsBranch, MacroSeriesBranch))
            and branch.branch_id not in calculation_inputs
        ):
            refs.append(branch.branch_id)
    return tuple(dict.fromkeys(refs))

__all__ = ('_normalize_default_chart_window', '_explicit_quarter_growth_requested', '_explicit_annual_growth_requested', '_normalize_chart_branch', '_default_chart_references')  # noqa: E501
