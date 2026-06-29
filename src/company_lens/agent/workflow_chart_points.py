from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _latest_observation_at_or_before(
    dates: Sequence[date],
    target: date,
) -> date | None:
    candidates = [observed_at for observed_at in dates if observed_at <= target]
    return max(candidates) if candidates else None


def _chart_series_points(
    reference: str,
    state: AgentState,
) -> tuple[ChartSeries, dict[date, tuple[Decimal, tuple[str, ...]]]]:
    observations = _numeric_series_for_chart(reference, state)
    if observations is not None:
        dated = tuple(
            item for item in observations if item.observed_at is not None and item.value is not None
        )
        if not dated:
            raise ValueError("Chart source has no dated observations.")
        units = {item.unit for item in dated}
        if len(units) != 1:
            raise ValueError("Chart source contains incompatible units.")
        return (
            ChartSeries(key=reference, label=dated[0].label, unit=units.pop()),
            {
                cast(date, item.observed_at): (cast(Decimal, item.value), (item.source_url,))
                for item in dated
            },
        )
    calculation = next(
        (item for item in state.get("calculations", ()) if item.branch_id == reference),
        None,
    )
    if calculation is None:
        raise ValueError("Chart dataset reference is missing.")
    if any(point.observed_at is None for point in calculation.result.values):
        raise ValueError("Scalar calculations without dates cannot be charted.")
    return (
        ChartSeries(
            key=reference,
            label=_calculation_series_label(calculation.result),
            unit=calculation.result.unit,
        ),
        {
            cast(date, point.observed_at): (point.value, calculation.result.sources)
            for point in calculation.result.values
        },
    )


def _calculation_series_label(result: CalculationResult) -> str:
    label = (
        result.values[-1].label
        if result.values
        else result.inputs[-1].label
        if result.inputs
        else "Calculation"
    )
    base = _strip_trailing_iso_date(label).strip()
    operation = _short_operation_label(result.operation)
    if operation and operation.casefold() not in base.casefold():
        return f"{base} {operation}"
    return base or operation or result.operation.replace("_", " ")


def _strip_trailing_iso_date(value: str) -> str:
    parts = value.rsplit(" ", 1)
    if len(parts) != 2:
        return value
    try:
        date.fromisoformat(parts[1])
    except ValueError:
        return value
    return parts[0]


def _short_operation_label(operation: str) -> str:
    return {
        "year_over_year_growth": "YoY",
        "quarter_over_quarter_growth": "QoQ",
        "percentage_change": "change",
        "absolute_change": "change",
        "compound_annual_growth_rate": "CAGR",
        "cagr": "CAGR",
        "rolling_average": "average",
        "correlation": "correlation",
        "margin": "margin",
    }.get(operation, operation.replace("_", " "))


def _numeric_series_for_chart(
    reference: str, state: AgentState
) -> tuple[NumericObservation, ...] | None:
    if any(item.branch_id == reference for item in state.get("financial_results", ())):
        return _numeric_series(reference, state)
    if any(item.branch_id == reference for item in state.get("macro_results", ())):
        return _numeric_series(reference, state)
    return None


def _default_chart_macro_evidence_keys(
    state: AgentState,
) -> set[tuple[str, str, date]] | None:
    plan = state.get("execution_plan")
    if plan is None or DEFAULT_CHART_WINDOW_REASON not in plan.reason_codes:
        return None
    calculation_dates = tuple(
        point.observed_at
        for calculation in state.get("calculations", ())
        for point in calculation.result.values
        if point.observed_at is not None
    )
    if not calculation_dates:
        return None
    allowed: set[tuple[str, str, date]] = set()
    for macro_branch in state.get("macro_results", ()):
        observations_by_series: dict[str, tuple[date, ...]] = {}
        for observation in macro_branch.result.observations:
            if observation.is_missing or observation.value is None:
                continue
            observations_by_series.setdefault(observation.series_id, ())
            observations_by_series[observation.series_id] = (
                *observations_by_series[observation.series_id],
                observation.observed_at,
            )
        for series_id, observed_dates in observations_by_series.items():
            for calculation_date in calculation_dates:
                matched_at = _latest_observation_at_or_before(observed_dates, calculation_date)
                if matched_at is not None:
                    allowed.add((macro_branch.branch_id, series_id, matched_at))
    return allowed

__all__ = ('_latest_observation_at_or_before', '_chart_series_points', '_calculation_series_label', '_strip_trailing_iso_date', '_short_operation_label', '_numeric_series_for_chart', '_default_chart_macro_evidence_keys')  # noqa: E501
