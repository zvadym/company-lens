from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _execute_calculation(branch: CalculationBranch, state: AgentState) -> CalculationResult:
    operation = branch.operation
    series = [
        _numeric_series(reference, state, operation=operation) for reference in branch.input_refs
    ]
    if operation == "quarter_over_quarter_growth":
        previous, current = _two_observations(series[0])
        return quarter_over_quarter_growth(current, previous)
    if operation == "year_over_year_growth":
        return year_over_year_growth_series(series[0])
    if operation == "cagr":
        start, end = _endpoints(series[0])
        assert branch.years is not None
        return compound_annual_growth_rate(end, start, years=branch.years)
    if operation == "margin":
        return margin(_latest(series[0]), _latest(series[1]))
    if operation == "absolute_change":
        previous, current = _endpoints(series[0])
        return absolute_change(current, previous)
    if operation == "percentage_change":
        previous, current = _endpoints(series[0])
        return percentage_change(current, previous)
    if operation == "rolling_average":
        assert branch.window is not None
        return rolling_average(series[0], window=branch.window)
    if operation == "normalised_index":
        return normalised_index(series[0], base=branch.base)
    return correlation(series[0], series[1])


def _normalize_calculation_result(
    branch: CalculationBranch,
    result: CalculationResult,
    state: AgentState,
) -> CalculationResult:
    plan = state.get("execution_plan")
    if (
        plan is None
        or DEFAULT_CHART_WINDOW_REASON not in plan.reason_codes
        or branch.operation != "year_over_year_growth"
        or len(result.values) <= DEFAULT_CHART_QUARTERS
    ):
        return result
    return result.model_copy(update={"values": result.values[-DEFAULT_CHART_QUARTERS:]})


def _numeric_series(
    branch_id: str,
    state: AgentState,
    *,
    operation: str | None = None,
) -> tuple[NumericObservation, ...]:
    financial = next(
        (item for item in state.get("financial_results", ()) if item.branch_id == branch_id),
        None,
    )
    if financial is not None:
        selected = _select_financial_observations(
            financial.result.observations,
            operation,
            requested_fiscal_years=financial.result.query.fiscal_years,
        )
        observations = tuple(
            NumericObservation(
                label=f"{item.company_name} {item.metric} {item.period_end.isoformat()}",
                value=item.value,
                unit=item.unit,
                source_url=item.source_url,
                observed_at=item.period_end,
            )
            for item in selected
        )
        return tuple(sorted(observations, key=lambda item: item.observed_at or datetime.min.date()))
    macro = next(
        (item for item in state.get("macro_results", ()) if item.branch_id == branch_id),
        None,
    )
    if macro is None:
        raise ValueError("Numeric branch result is missing.")
    observations = tuple(
        NumericObservation(
            label=f"{item.series_id} {item.observed_at.isoformat()}",
            value=item.value,
            unit=item.unit,
            source_url=item.source_url,
            observed_at=item.observed_at,
        )
        for item in macro.result.observations
        if not item.is_missing
    )
    return tuple(sorted(observations, key=lambda item: item.observed_at or datetime.min.date()))


def _select_financial_observations(
    observations: Sequence[FinancialFactObservation],
    operation: str | None,
    *,
    requested_fiscal_years: tuple[int, ...] = (),
) -> tuple[FinancialFactObservation, ...]:
    deduplicated: dict[tuple[object, ...], FinancialFactObservation] = {}
    for item in observations:
        key = (
            item.company_id,
            item.metric,
            item.unit,
            item.period_start,
            item.period_end,
            item.period_type,
            item.fiscal_period,
        )
        existing = deduplicated.get(key)
        if existing is None or _financial_filing_key(item) > _financial_filing_key(existing):
            deduplicated[key] = item
    ordered = tuple(
        sorted(
            deduplicated.values(),
            key=lambda item: (item.period_end, *_financial_filing_key(item)),
        )
    )
    if operation not in {"year_over_year_growth", "quarter_over_quarter_growth"}:
        return ordered
    series_keys = {(item.company_id, item.metric, item.unit) for item in ordered}
    if len(series_keys) != 1:
        raise ValueError("Growth requires exactly one company, metric, and unit series.")
    if operation == "quarter_over_quarter_growth":
        quarters = tuple(item for item in ordered if item.period_type == "quarter")
        if len(quarters) < 2:
            raise ValueError("Quarter-over-quarter growth requires two quarterly observations.")
        return quarters[-2:]
    annual = tuple(item for item in ordered if item.period_type == "annual")
    if len(annual) >= 2:
        annual = _deduplicate_annual_observations_for_growth(annual)
        if requested_fiscal_years:
            first_year = min(requested_fiscal_years) - 1
            last_year = max(requested_fiscal_years)
            annual = tuple(
                item for item in annual if first_year <= item.period_end.year <= last_year
            )
        if len(annual) < 2:
            raise ValueError("Year-over-year growth requires a prior-year baseline.")
        return annual
    comparable = tuple(item for item in ordered if item.period_type in {"quarter", "year_to_date"})
    if len(comparable) < 2:
        raise ValueError("Year-over-year growth requires two comparable observations.")
    has_matching_pair = any(
        any(_same_reporting_period(previous, current) for previous in comparable[:index])
        for index, current in enumerate(comparable)
    )
    if not has_matching_pair:
        raise ValueError("Year-over-year growth requires matching reporting periods.")
    return comparable


def _deduplicate_annual_observations_for_growth(
    observations: Sequence[FinancialFactObservation],
) -> tuple[FinancialFactObservation, ...]:
    by_period: dict[tuple[object, ...], FinancialFactObservation] = {}
    for item in observations:
        # Annual facts are often restated in later filings and may appear once with FY and once
        # with an empty fiscal_period. YoY charts need one value per plotted period_end.
        key = (item.company_id, item.metric, item.unit, item.period_end)
        existing = by_period.get(key)
        if existing is None or _financial_filing_key(item) > _financial_filing_key(existing):
            by_period[key] = item
    return tuple(
        sorted(
            by_period.values(),
            key=lambda item: (item.period_end, *_financial_filing_key(item)),
        )
    )


def _financial_filing_key(item: FinancialFactObservation) -> tuple[date, str, str]:
    return item.filed_date or date.min, item.accession_number or "", str(item.id)


def _same_reporting_period(
    previous: FinancialFactObservation,
    current: FinancialFactObservation,
) -> bool:
    if previous.period_type != current.period_type:
        return False
    if previous.fiscal_period and current.fiscal_period:
        return previous.fiscal_period == current.fiscal_period
    return (previous.period_end.month, previous.period_end.day) == (
        current.period_end.month,
        current.period_end.day,
    )


def _two_observations(
    observations: Sequence[NumericObservation],
) -> tuple[NumericObservation, NumericObservation]:
    if len(observations) != 2:
        raise ValueError("Calculation requires exactly two ordered observations.")
    return observations[0], observations[1]


def _endpoints(
    observations: Sequence[NumericObservation],
) -> tuple[NumericObservation, NumericObservation]:
    if len(observations) < 2:
        raise ValueError("Calculation requires at least two observations.")
    return observations[0], observations[-1]


def _latest(observations: Sequence[NumericObservation]) -> NumericObservation:
    if len(observations) != 1:
        raise ValueError("Scalar calculation input must contain exactly one observation.")
    return observations[0]


__all__ = (
    "_execute_calculation",
    "_normalize_calculation_result",
    "_numeric_series",
    "_select_financial_observations",
    "_deduplicate_annual_observations_for_growth",
    "_financial_filing_key",
    "_same_reporting_period",
    "_two_observations",
    "_endpoints",
    "_latest",
)  # noqa: E501
