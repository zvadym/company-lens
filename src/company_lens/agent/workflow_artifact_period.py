from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _fallback_recent_artifact_period_plan(
    question: str,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    memory: SessionMemory | None,
) -> ExecutionPlan | None:
    if memory is None or not analysis.is_follow_up or not analysis.chart_requested:
        return None
    if not _requests_period_override(question, analysis):
        return None
    artifact = _selected_chart_artifact(memory)
    if artifact is None or not artifact.company_ids:
        return None
    company_ids = tuple(
        company_id for company_id in artifact.company_ids if company_id in set(resolved.company_ids)
    )
    if not company_ids:
        return None
    metric = (artifact.metrics or resolved.metrics or ("revenue",))[0]
    operation = _artifact_growth_operation(artifact) or _previous_growth_operation(memory)
    if operation is None:
        return None
    period = _period_override(question)
    if period is None:
        return None
    source_period_start, source_period_end = _financial_source_period(period, operation)
    branches: list[ExecutionBranch] = []
    growth_refs: list[str] = []
    for index, company_id in enumerate(company_ids, start=1):
        facts_id = f"artifact_{index}_{metric}_facts"
        growth_id = f"artifact_{index}_{metric}_growth"
        branches.append(
            FinancialFactsBranch(
                branch_id=facts_id,
                request=FinancialFactQuery(
                    company_ids=(company_id,),
                    metrics=(metric,),
                    period_start=source_period_start,
                    period_end=source_period_end,
                    period_types=("quarter",),
                    limit=DEFAULT_CHART_QUARTERLY_FACT_LIMIT,
                ),
            )
        )
        branches.append(
            CalculationBranch(
                branch_id=growth_id,
                operation=operation,
                input_refs=(facts_id,),
                depends_on=(facts_id,),
            )
        )
        growth_refs.append(growth_id)
    chart_type = _artifact_chart_type(artifact)
    branches.append(
        ChartBranch(
            branch_id="artifact_period_chart",
            chart_type=chart_type,
            dataset_ref=growth_refs[0],
            depends_on=tuple(growth_refs),
            title=artifact.title or f"{metric.title()} growth comparison",
        )
    )
    return ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=tuple(branches),
        reason_codes=("deterministic_recent_artifact_period_plan",),
    )


def _requests_period_override(question: str, analysis: QuestionAnalysis) -> bool:
    normalized = question.casefold()
    if any(
        marker in reason
        for reason in analysis.reason_codes
        for marker in ("change_period", "period_override", "date_range")
    ):
        return True
    return _period_override(question) is not None and any(
        marker in normalized for marker in ("same", "такий", "такий сам", "цей", "граф")
    )


def _period_override(question: str) -> tuple[date, date] | None:
    years = [int(match.group(0)) for match in re.finditer(r"\b20\d{2}\b", question)]
    if not years:
        return None
    start_year = min(years)
    end_year = max(years)
    return date(start_year, 1, 1), date(end_year, 12, 31)


def _artifact_growth_operation(artifact: SessionArtifactContext) -> CalculationOperation | None:
    for operation in artifact.calculations:
        if operation in {
            "quarter_over_quarter_growth",
            "year_over_year_growth",
            "percentage_change",
            "absolute_change",
            "cagr",
            "margin",
            "rolling_average",
            "normalised_index",
            "correlation",
        }:
            return cast(CalculationOperation, operation)
    return None


def _artifact_chart_type(
    artifact: SessionArtifactContext,
) -> ChartKind:
    if artifact.chart_type in {"line", "bar", "area", "scatter"}:
        return cast(ChartKind, artifact.chart_type)
    return "line"

__all__ = ('_fallback_recent_artifact_period_plan', '_requests_period_override', '_period_override', '_artifact_growth_operation', '_artifact_chart_type')  # noqa: E501
