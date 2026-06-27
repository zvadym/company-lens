from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from datetime import date
from decimal import Decimal, localcontext

from company_lens.analytics.schemas import (
    CalculationPoint,
    CalculationResult,
    NumericObservation,
)

PERCENT = Decimal("100")


def quarter_over_quarter_growth(
    current: NumericObservation, previous_quarter: NumericObservation
) -> CalculationResult:
    return _percentage_change(
        "quarter_over_quarter_growth",
        current,
        previous_quarter,
        "(current / prior_quarter - 1) * 100",
    )


def year_over_year_growth(
    current: NumericObservation, previous_year: NumericObservation
) -> CalculationResult:
    return _percentage_change(
        "year_over_year_growth", current, previous_year, "(current / prior_year - 1) * 100"
    )


def year_over_year_growth_series(
    observations: Sequence[NumericObservation],
) -> CalculationResult:
    if len(observations) < 2:
        raise ValueError("Year-over-year growth requires at least two observations.")
    _require_compatible(observations)
    dated = tuple(item for item in observations if item.observed_at is not None)
    if len(dated) == len(observations):
        dated_points = _dated_year_over_year_points(dated)
        if dated_points:
            return _result(
                "year_over_year_growth",
                tuple(dated_points),
                observations,
                "(current / prior_year - 1) * 100",
                "percent",
            )
    points: list[CalculationPoint] = []
    for previous, current in zip(observations, observations[1:], strict=False):
        if (
            previous.observed_at is not None
            and current.observed_at is not None
            and current.observed_at.year - previous.observed_at.year != 1
        ):
            raise ValueError("Year-over-year growth requires consecutive annual observations.")
        current_value, previous_value = _values((current, previous))
        _require_nonzero(previous_value, "Previous value")
        points.append(
            CalculationPoint(
                label=current.label,
                observed_at=current.observed_at,
                value=_decimal((current_value / previous_value - 1) * PERCENT),
            )
        )
    return _result(
        "year_over_year_growth",
        tuple(points),
        observations,
        "(current / prior_year - 1) * 100",
        "percent",
    )


def _dated_year_over_year_points(
    observations: Sequence[NumericObservation],
) -> list[CalculationPoint]:
    by_date = {item.observed_at: item for item in observations if item.observed_at is not None}
    points: list[CalculationPoint] = []
    for current in observations:
        assert current.observed_at is not None
        with suppress(ValueError):
            prior_date = current.observed_at.replace(year=current.observed_at.year - 1)
            previous = by_date.get(prior_date) or _nearest_prior_year_observation(
                observations,
                prior_date,
            )
            if previous is None:
                continue
            current_value, previous_value = _values((current, previous))
            _require_nonzero(previous_value, "Previous value")
            points.append(
                CalculationPoint(
                    label=current.label,
                    observed_at=current.observed_at,
                    value=_decimal((current_value / previous_value - 1) * PERCENT),
                )
            )
    return points


def _nearest_prior_year_observation(
    observations: Sequence[NumericObservation],
    target: date,
) -> NumericObservation | None:
    candidates = tuple(
        (item.observed_at, item)
        for item in observations
        if item.observed_at is not None and item.observed_at.year == target.year
    )
    if not candidates:
        return None
    closest_date, closest = min(candidates, key=lambda item: abs((item[0] - target).days))
    if abs((closest_date - target).days) > 7:
        return None
    return closest


def compound_annual_growth_rate(
    end: NumericObservation,
    start: NumericObservation,
    *,
    years: Decimal,
) -> CalculationResult:
    _require_compatible((end, start))
    end_value, start_value = _values((end, start))
    if start_value <= 0 or end_value < 0:
        raise ValueError("CAGR requires a positive start value and a non-negative end value.")
    if years <= 0:
        raise ValueError("CAGR years must be greater than zero.")
    with localcontext() as context:
        context.prec = 28
        value = ((end_value / start_value) ** (Decimal(1) / years) - 1) * PERCENT
    return _scalar(
        "cagr",
        value,
        (start, end),
        "((end / start) ** (1 / years) - 1) * 100",
        "percent",
        label=end.label,
        observed_at=end.observed_at,
    )


def margin(numerator: NumericObservation, denominator: NumericObservation) -> CalculationResult:
    _require_compatible((numerator, denominator))
    numerator_value, denominator_value = _values((numerator, denominator))
    _require_nonzero(denominator_value, "Margin denominator")
    return _scalar(
        "margin",
        numerator_value / denominator_value * PERCENT,
        (numerator, denominator),
        "numerator / denominator * 100",
        "percent",
        label=numerator.label,
        observed_at=(
            numerator.observed_at if numerator.observed_at == denominator.observed_at else None
        ),
    )


def absolute_change(current: NumericObservation, previous: NumericObservation) -> CalculationResult:
    _require_compatible((current, previous))
    current_value, previous_value = _values((current, previous))
    return _scalar(
        "absolute_change",
        current_value - previous_value,
        (previous, current),
        "current - previous",
        current.unit,
        label=current.label,
        observed_at=current.observed_at,
    )


def percentage_change(
    current: NumericObservation, previous: NumericObservation
) -> CalculationResult:
    return _percentage_change(
        "percentage_change", current, previous, "(current / previous - 1) * 100"
    )


def rolling_average(
    observations: Sequence[NumericObservation], *, window: int
) -> CalculationResult:
    if window < 1:
        raise ValueError("Rolling-average window must be at least one.")
    if len(observations) < window:
        raise ValueError("Rolling-average window exceeds the observation count.")
    _require_compatible(observations)
    values = _values(observations)
    points = tuple(
        CalculationPoint(
            label=observations[index].label,
            observed_at=observations[index].observed_at,
            value=_decimal(sum(values[index - window + 1 : index + 1]) / Decimal(window)),
        )
        for index in range(window - 1, len(observations))
    )
    return _result(
        "rolling_average",
        points,
        observations,
        f"sum(window[{window}]) / {window}",
        observations[0].unit,
    )


def normalised_index(
    observations: Sequence[NumericObservation], *, base: Decimal = Decimal("100")
) -> CalculationResult:
    if not observations:
        raise ValueError("A normalised index requires observations.")
    _require_compatible(observations)
    values = _values(observations)
    _require_nonzero(values[0], "Normalised-index base observation")
    points = tuple(
        CalculationPoint(
            label=item.label,
            observed_at=item.observed_at,
            value=_decimal(value / values[0] * base),
        )
        for item, value in zip(observations, values, strict=True)
    )
    return _result(
        "normalised_index",
        points,
        observations,
        f"value / first_value * {base}",
        "index",
    )


def correlation(
    left: Sequence[NumericObservation], right: Sequence[NumericObservation]
) -> CalculationResult:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("Correlation requires two equally sized series with at least two points.")
    if [item.observed_at for item in left] != [item.observed_at for item in right]:
        raise ValueError("Correlation inputs must be aligned to identical observation dates.")
    _require_compatible(left)
    _require_compatible(right)
    left_values = _values(left)
    right_values = _values(right)
    with localcontext() as context:
        context.prec = 28
        count = Decimal(len(left_values))
        left_mean = sum(left_values) / count
        right_mean = sum(right_values) / count
        covariance = sum(
            (
                (x - left_mean) * (y - right_mean)
                for x, y in zip(left_values, right_values, strict=True)
            ),
            Decimal(0),
        )
        left_variance = sum(((value - left_mean) ** 2 for value in left_values), Decimal(0))
        right_variance = sum(((value - right_mean) ** 2 for value in right_values), Decimal(0))
        if left_variance == 0 or right_variance == 0:
            raise ValueError("Correlation is undefined for a constant series.")
        value = covariance / (left_variance * right_variance).sqrt()
    return _scalar(
        "correlation",
        value,
        (*left, *right),
        "sum((x-x_mean)*(y-y_mean)) / sqrt(sum((x-x_mean)^2)*sum((y-y_mean)^2))",
        "coefficient",
        warnings=("Correlation does not establish causation.",),
    )


def _percentage_change(
    operation: str,
    current: NumericObservation,
    previous: NumericObservation,
    formula: str,
) -> CalculationResult:
    _require_compatible((current, previous))
    current_value, previous_value = _values((current, previous))
    _require_nonzero(previous_value, "Previous value")
    return _scalar(
        operation,
        (current_value / previous_value - 1) * PERCENT,
        (previous, current),
        formula,
        "percent",
        label=current.label,
        observed_at=current.observed_at,
    )


def _require_compatible(observations: Sequence[NumericObservation]) -> None:
    if not observations:
        raise ValueError("At least one observation is required.")
    units = {item.unit for item in observations}
    if "" in units or len(units) != 1:
        raise ValueError(f"Incompatible units: {sorted(units)}")


def _values(observations: Sequence[NumericObservation]) -> tuple[Decimal, ...]:
    missing = [item.label for item in observations if item.value is None]
    if missing:
        raise ValueError("Missing observation values: " + ", ".join(missing))
    return tuple(item.value for item in observations if item.value is not None)


def _require_nonzero(value: Decimal, label: str) -> None:
    if value == 0:
        raise ValueError(f"{label} cannot be zero.")


def _scalar(
    operation: str,
    value: Decimal,
    inputs: Sequence[NumericObservation],
    formula: str,
    unit: str,
    *,
    label: str | None = None,
    observed_at: date | None = None,
    warnings: tuple[str, ...] = (),
) -> CalculationResult:
    point = CalculationPoint(
        label=label or operation,
        value=_decimal(value),
        observed_at=observed_at,
    )
    return _result(operation, (point,), inputs, formula, unit, warnings=warnings)


def _result(
    operation: str,
    values: tuple[CalculationPoint, ...],
    inputs: Sequence[NumericObservation],
    formula: str,
    unit: str,
    *,
    warnings: tuple[str, ...] = (),
) -> CalculationResult:
    return CalculationResult(
        operation=operation,
        values=values,
        inputs=tuple(inputs),
        formula=formula,
        unit=unit,
        sources=tuple(dict.fromkeys(item.source_url for item in inputs)),
        warnings=warnings,
    )


def _decimal(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        return +value
