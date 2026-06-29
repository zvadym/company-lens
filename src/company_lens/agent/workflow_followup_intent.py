from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _requests_plan_replay(question: str, analysis: QuestionAnalysis) -> bool:
    replay_capabilities = {
        AgentCapability.FINANCIAL_FACTS,
        AgentCapability.CALCULATIONS,
        AgentCapability.CHART,
    }
    if not analysis.chart_requested and not replay_capabilities.intersection(
        analysis.required_capabilities
    ):
        return False
    if _requested_chart_type(question) is not None:
        return True
    if _requests_period_override(question, analysis):
        return True
    if _analysis_requests_add_series(analysis) or _question_requests_add_series(question):
        return True
    if any(
        marker in reason
        for reason in analysis.reason_codes
        for marker in (
            "same",
            "repeat",
            "previous",
            "follow_up_chart",
            "same_chart",
            "same_data",
        )
    ):
        return True
    return _question_references_previous_work(question)


def _question_references_previous_work(question: str) -> bool:
    normalized = question.casefold()
    return any(
        marker in normalized
        for marker in (
            "same",
            "same data",
            "same chart",
            "do the same",
            "previous chart",
            "that chart",
            "again",
            "те саме",
            "так само",
            "такий графік",
            "цей графік",
            "попередній графік",
            "на цих дан",
            "на цих самих дан",
            "цих самих дан",
            "тих самих дан",
        )
    )


def _question_requests_chart(question: str) -> bool:
    normalized = question.casefold()
    return _requested_chart_type(question) is not None or any(
        marker in normalized for marker in ("chart", "graph", "plot", "графік", "граф", "діаграм")
    )


def _resolved_period_override(
    question: str,
    resolved: ResolvedQuery,
) -> tuple[date, date] | None:
    period = _period_override(question)
    if period is not None:
        return period
    if resolved.dates:
        return min(resolved.dates), max(resolved.dates)
    return None


def _requested_chart_type(question: str) -> ChartKind | None:
    normalized = question.casefold()
    markers: tuple[tuple[ChartKind, tuple[str, ...]], ...] = (
        ("bar", ("bar chart", "bar graph", "стовп", "гістограм", "bar ")),
        ("line", ("line chart", "line graph", "лінійн", "лінійний")),
        ("area", ("area chart", "area graph")),
        ("scatter", ("scatter chart", "scatter plot", "точков")),
    )
    for chart_type, chart_markers in markers:
        if any(marker in normalized for marker in chart_markers):
            return chart_type
    return None


def _first_financial_branch(plan: ExecutionPlan) -> FinancialFactsBranch | None:
    return next(
        (branch for branch in plan.branches if isinstance(branch, FinancialFactsBranch)),
        None,
    )


def _first_single_input_financial_calculation(
    plan: ExecutionPlan,
) -> CalculationBranch | None:
    branches = {branch.branch_id: branch for branch in plan.branches}
    for branch in plan.branches:
        if not isinstance(branch, CalculationBranch) or len(branch.input_refs) != 1:
            continue
        # Multi-input operations need their full source topology, so they remain model-planned.
        input_branch = branches.get(branch.input_refs[0])
        if isinstance(input_branch, FinancialFactsBranch):
            return branch
    return None


def _previous_chart_branch(plan: ExecutionPlan) -> ChartBranch | None:
    for branch in reversed(plan.branches):
        if isinstance(branch, ChartBranch):
            return branch
    return None


def _plan_company_ids(plan: ExecutionPlan) -> tuple[uuid.UUID, ...]:
    company_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for branch in plan.branches:
        if not isinstance(branch, FinancialFactsBranch):
            continue
        for company_id in branch.request.company_ids:
            if company_id in seen:
                continue
            seen.add(company_id)
            company_ids.append(company_id)
    return tuple(company_ids)


def _branch_id_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9_]+", "_", value.casefold()).strip("_")
    if not token:
        return "metric"
    if not token[0].isalpha():
        token = f"metric_{token}"
    return token


def _replayed_chart_title(
    metric: str,
    calculation: CalculationBranch | None,
    previous_chart: ChartBranch | None,
) -> str:
    if previous_chart is not None:
        return previous_chart.title
    operation = calculation.operation.replace("_", " ") if calculation is not None else "values"
    return f"{metric.replace('_', ' ').title()} {operation.title()}"


__all__ = (
    "_requests_plan_replay",
    "_question_references_previous_work",
    "_question_requests_chart",
    "_resolved_period_override",
    "_requested_chart_type",
    "_first_financial_branch",
    "_first_single_input_financial_calculation",
    "_previous_chart_branch",
    "_plan_company_ids",
    "_branch_id_token",
    "_replayed_chart_title",
)  # noqa: E501
