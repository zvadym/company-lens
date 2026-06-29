from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _fallback_multi_company_growth_chart_plan(
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    memory: SessionMemory | None,
) -> ExecutionPlan | None:
    if not analysis.chart_requested or len(resolved.company_ids) < 2:
        return None
    required = set(analysis.required_capabilities)
    if not {
        AgentCapability.FINANCIAL_FACTS,
        AgentCapability.CHART,
    }.issubset(required):
        return None
    previous_operation = _previous_growth_operation(memory)
    if AgentCapability.CALCULATIONS not in required and previous_operation is None:
        return None
    metric = resolved.metrics[0] if resolved.metrics else "revenue"
    operation = previous_operation or "year_over_year_growth"
    branches: list[ExecutionBranch] = []
    calculation_refs: list[str] = []
    for index, company_id in enumerate(resolved.company_ids, start=1):
        fact_id = f"company_{index}_{metric}_facts"
        growth_id = f"company_{index}_{metric}_growth"
        branches.append(
            FinancialFactsBranch(
                branch_id=fact_id,
                request=FinancialFactQuery(
                    company_ids=(company_id,),
                    metrics=(metric,),
                    period_types=("quarter",),
                    limit=DEFAULT_CHART_QUARTERLY_FACT_LIMIT,
                ),
            )
        )
        branches.append(
            CalculationBranch(
                branch_id=growth_id,
                operation=operation,
                input_refs=(fact_id,),
                depends_on=(fact_id,),
            )
        )
        calculation_refs.append(growth_id)
    branches.append(
        ChartBranch(
            branch_id="company_growth_chart",
            chart_type="line",
            dataset_ref=calculation_refs[0],
            depends_on=tuple(calculation_refs),
            title=f"{metric.title()} growth comparison",
        )
    )
    return ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=tuple(branches),
        reason_codes=("deterministic_multi_company_growth_chart_plan",),
    )


def _needs_multi_company_growth_chart_fallback(
    plan: ExecutionPlan,
    resolved: ResolvedQuery,
) -> bool:
    if len(resolved.company_ids) < 2:
        return False
    chart = next((branch for branch in plan.branches if isinstance(branch, ChartBranch)), None)
    if chart is None:
        return True
    chart_refs = set(_chart_references(chart)) | set(_default_chart_references(plan))
    branches_by_id = {branch.branch_id: branch for branch in plan.branches}
    plotted_growth_companies: set[uuid.UUID] = set()
    for reference in chart_refs:
        branch = branches_by_id.get(reference)
        if not isinstance(branch, CalculationBranch):
            continue
        if branch.operation not in {
            "quarter_over_quarter_growth",
            "year_over_year_growth",
            "percentage_change",
        }:
            continue
        for input_ref in branch.input_refs:
            input_branch = branches_by_id.get(input_ref)
            if (
                isinstance(input_branch, FinancialFactsBranch)
                and len(input_branch.request.company_ids) == 1
            ):
                plotted_growth_companies.add(input_branch.request.company_ids[0])
    return not set(resolved.company_ids).issubset(plotted_growth_companies)


def _previous_growth_operation(memory: SessionMemory | None) -> CalculationOperation | None:
    if memory is None or memory.last_execution_plan is None:
        return None
    for branch in reversed(memory.last_execution_plan.branches):
        if isinstance(branch, CalculationBranch) and branch.operation in {
            "quarter_over_quarter_growth",
            "year_over_year_growth",
            "percentage_change",
        }:
            return branch.operation
    return None

__all__ = ('_fallback_multi_company_growth_chart_plan', '_needs_multi_company_growth_chart_fallback', '_previous_growth_operation')  # noqa: E501
