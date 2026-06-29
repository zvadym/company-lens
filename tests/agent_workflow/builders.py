from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .shared import *  # noqa: F403

# ruff: noqa: F405


def _financial_branch() -> FinancialFactsBranch:
    return FinancialFactsBranch(
        branch_id="financial",
        request=FinancialFactQuery(
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
            fiscal_years=(2024, 2025),
        ),
    )


def _macro_branch() -> MacroSeriesBranch:
    return MacroSeriesBranch(
        branch_id="macro",
        request=FredSeriesQuery(series_ids=("FEDFUNDS",)),
    )


def _model_execution_plan(plan: ExecutionPlan) -> ModelExecutionPlan:
    branches: list[ModelExecutionBranch] = []
    for branch in plan.branches:
        common: dict[str, object] = {
            "kind": branch.kind,
            "branch_id": branch.branch_id,
            "depends_on": branch.depends_on,
            "optional": branch.optional,
        }
        if isinstance(branch, DocumentRetrievalBranch):
            common["retrieval_request"] = branch.request
        elif isinstance(branch, FinancialFactsBranch):
            common["financial_request"] = branch.request
        elif isinstance(branch, MacroSeriesBranch):
            common["macro_request"] = branch.request
        elif isinstance(branch, CalculationBranch):
            common.update(
                {
                    "operation": branch.operation,
                    "input_refs": branch.input_refs,
                    "years": float(branch.years) if branch.years is not None else None,
                    "window": branch.window,
                    "base": float(branch.base),
                }
            )
        else:
            common.update(
                {
                    "chart_type": branch.chart_type,
                    "dataset_ref": branch.dataset_ref,
                    "title": branch.title,
                    "x_label": branch.x_label,
                }
            )
        branches.append(ModelExecutionBranch.model_validate(common))
    return ModelExecutionPlan(
        route=plan.route,
        branches=tuple(branches),
        requires_citations=plan.requires_citations,
        reason_codes=plan.reason_codes,
    )


def _previous_revenue_growth_chart_plan(company_id: uuid.UUID) -> ExecutionPlan:
    facts = FinancialFactsBranch(
        branch_id="previous_revenue",
        request=FinancialFactQuery(
            company_ids=(company_id,),
            metrics=("revenue",),
            period_types=("quarter",),
            limit=8,
        ),
    )
    growth = CalculationBranch(
        branch_id="previous_growth",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    chart = ChartBranch(
        branch_id="previous_chart",
        chart_type="line",
        dataset_ref=growth.branch_id,
        depends_on=(growth.branch_id,),
        title="Revenue growth",
    )
    return ExecutionPlan(route=ResearchRoute.CALCULATION, branches=(facts, growth, chart))


def _financial_observation(period_end: date, value: Decimal) -> FinancialFactObservation:
    return FinancialFactObservation(
        id=FACT_ID,
        company_id=COMPANY_ID,
        company_name="Cloudflare",
        ticker="NET",
        metric="revenue",
        value=value,
        unit="USD",
        period_start=date(period_end.year, 1, 1),
        period_end=period_end,
        period_type="annual",
        fiscal_year=period_end.year,
        fiscal_period="FY",
        form="10-K",
        filed_date=period_end,
        accession_number=f"{period_end.year}-fixture",
        taxonomy="us-gaap",
        concept="Revenue",
        frame=None,
        is_amendment=False,
        has_conflict=False,
        mapping_version="v1",
        source_url=f"https://sec.example/{period_end.year}",
    )


__all__ = (
    "_financial_branch",
    "_macro_branch",
    "_model_execution_plan",
    "_previous_revenue_growth_chart_plan",
    "_financial_observation",
)  # noqa: E501
