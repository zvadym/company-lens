from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _replay_financial_follow_up_plan(
    question: str,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    previous_plan: ExecutionPlan,
) -> ExecutionPlan | None:
    template_facts = _first_financial_branch(previous_plan)
    if template_facts is None:
        return None
    template_calculation = _first_single_input_financial_calculation(previous_plan)
    company_ids = resolved.company_ids or _plan_company_ids(previous_plan)
    metric = (resolved.metrics or template_facts.request.metrics or ("revenue",))[0]
    if not company_ids:
        return None

    period = _resolved_period_override(question, resolved)
    branches: list[ExecutionBranch] = []
    numeric_refs: list[str] = []
    for index, company_id in enumerate(company_ids, start=1):
        fact_id = f"replay_{index}_{_branch_id_token(metric)}_facts"
        branches.append(
            FinancialFactsBranch(
                branch_id=fact_id,
                request=_replayed_financial_request(
                    template_facts.request,
                    company_id,
                    metric,
                    period,
                    template_calculation.operation if template_calculation is not None else None,
                ),
            )
        )
        if template_calculation is None:
            numeric_refs.append(fact_id)
            continue
        calculation_id = f"replay_{index}_{_branch_id_token(metric)}_calc"
        branches.append(
            template_calculation.model_copy(
                update={
                    "branch_id": calculation_id,
                    "input_refs": (fact_id,),
                    "depends_on": (fact_id,),
                }
            )
        )
        numeric_refs.append(calculation_id)

    macro_refs = _replayed_macro_branches(previous_plan, period)
    branches.extend(macro_refs)
    previous_chart = _previous_chart_branch(previous_plan)
    if analysis.chart_requested or previous_chart is not None:
        chart_refs = (*numeric_refs, *tuple(branch.branch_id for branch in macro_refs))
        if not chart_refs:
            return None
        chart_type = _requested_chart_type(question)
        branches.append(
            ChartBranch(
                branch_id="replay_chart",
                chart_type=chart_type
                or (previous_chart.chart_type if previous_chart is not None else "line"),
                dataset_ref=chart_refs[0],
                depends_on=chart_refs,
                title=_replayed_chart_title(metric, template_calculation, previous_chart),
            )
        )

    return _canonicalize_plan_route(
        ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=tuple(branches),
            reason_codes=("deterministic_follow_up_replay_plan",),
        )
    )


def _replayed_financial_request(
    template: FinancialFactQuery,
    company_id: uuid.UUID,
    metric: str,
    period: tuple[date, date] | None,
    operation: CalculationOperation | None,
) -> FinancialFactQuery:
    updates: dict[str, object] = {
        "company_ids": (company_id,),
        "tickers": (),
        "metrics": (metric,),
    }
    if period is not None:
        period_start, period_end = _financial_source_period(period, operation)
        updates.update(
            {
                "period_start": period_start,
                "period_end": period_end,
                "fiscal_years": (),
                "fiscal_periods": (),
            }
        )
    return template.model_copy(update=updates)


def _financial_source_period(
    period: tuple[date, date],
    operation: CalculationOperation | None,
) -> tuple[date, date]:
    period_start, period_end = period
    if operation == "year_over_year_growth":
        # YoY calculations need the prior-year baseline, while the plotted points
        # still begin at the user's requested start period.
        return _same_day_previous_year(period_start), period_end
    return period


def _same_day_previous_year(value: date) -> date:
    with suppress(ValueError):
        return value.replace(year=value.year - 1)
    return value.replace(year=value.year - 1, day=28)


def _replayed_macro_branches(
    previous_plan: ExecutionPlan,
    period: tuple[date, date] | None,
) -> list[MacroSeriesBranch]:
    macro_branches: list[MacroSeriesBranch] = []
    for branch in previous_plan.branches:
        if not isinstance(branch, MacroSeriesBranch):
            continue
        if period is None:
            macro_branches.append(branch)
            continue
        period_start, period_end = period
        macro_branches.append(
            branch.model_copy(
                update={
                    "request": branch.request.model_copy(
                        update={
                            "observation_start": period_start,
                            "observation_end": period_end,
                        }
                    )
                }
            )
        )
    return macro_branches

__all__ = ('_replay_financial_follow_up_plan', '_replayed_financial_request', '_financial_source_period', '_same_day_previous_year', '_replayed_macro_branches')  # noqa: E501
