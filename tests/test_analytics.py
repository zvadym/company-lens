from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from company_lens.analytics.calculations import (
    absolute_change,
    compound_annual_growth_rate,
    correlation,
    margin,
    normalised_index,
    percentage_change,
    quarter_over_quarter_growth,
    rolling_average,
    year_over_year_growth,
    year_over_year_growth_series,
)
from company_lens.analytics.charts import generate_chart_specification
from company_lens.analytics.schemas import (
    ChartPoint,
    ChartSeries,
    NumericObservation,
    ValidatedChartDataset,
)

SOURCE = "https://fred.stlouisfed.org/series/TEST"


def observation(
    label: str,
    value: str | None,
    *,
    unit: str = "USD",
    observed_at: date | None = None,
) -> NumericObservation:
    return NumericObservation(
        label=label,
        value=value,
        unit=unit,
        source_url=SOURCE,
        observed_at=observed_at,
    )


def test_deterministic_growth_change_cagr_and_margin() -> None:
    previous = observation("previous", "80", observed_at=date(2024, 12, 31))
    current = observation("current", "100", observed_at=date(2025, 3, 31))

    qoq = quarter_over_quarter_growth(current, previous)
    yoy = year_over_year_growth(current, previous)
    change = percentage_change(current, previous)
    absolute = absolute_change(current, previous)

    assert qoq.values[0].value == Decimal("25.00")
    assert qoq.values[0].observed_at == date(2025, 3, 31)
    assert yoy.values[0].value == Decimal("25.00")
    assert yoy.values[0].observed_at == date(2025, 3, 31)
    assert change.values[0].value == Decimal("25.00")
    assert change.values[0].observed_at == date(2025, 3, 31)
    assert absolute.values[0].value == Decimal("20")
    assert absolute.values[0].observed_at == date(2025, 3, 31)
    assert margin(observation("profit", "25"), current).values[0].value == Decimal("25.00")
    assert compound_annual_growth_rate(
        observation("end", "121"), observation("start", "100"), years=Decimal("2")
    ).values[0].value == Decimal("10.0")


def test_rolling_average_and_normalised_index_retain_inputs_and_sources() -> None:
    inputs = tuple(
        observation(
            f"m{index}",
            value,
            unit="percent",
            observed_at=date(2025, index, 1),
        )
        for index, value in enumerate(("2", "4", "6"), start=1)
    )

    average = rolling_average(inputs, window=2)
    index = normalised_index(inputs)

    assert [point.value for point in average.values] == [Decimal("3"), Decimal("5")]
    assert [point.value for point in index.values] == [
        Decimal("100"),
        Decimal("200"),
        Decimal("300"),
    ]
    assert average.inputs == inputs
    assert average.sources == (SOURCE,)
    assert average.formula == "sum(window[2]) / 2"


def test_year_over_year_growth_series_returns_every_dated_pair() -> None:
    inputs = tuple(
        observation(
            str(year),
            value,
            observed_at=date(year, 12, 31),
        )
        for year, value in zip(
            range(2022, 2026),
            ("975241000", "1296745000", "1669626000", "2167937000"),
            strict=True,
        )
    )

    result = year_over_year_growth_series(inputs)

    assert [point.observed_at for point in result.values] == [
        date(2023, 12, 31),
        date(2024, 12, 31),
        date(2025, 12, 31),
    ]
    assert [point.value.quantize(Decimal("0.1")) for point in result.values] == [
        Decimal("33.0"),
        Decimal("28.8"),
        Decimal("29.8"),
    ]
    assert result.inputs == inputs


def test_year_over_year_growth_series_matches_quarterly_prior_year_periods() -> None:
    inputs = tuple(
        observation(
            f"{year}Q{quarter}",
            value,
            observed_at=period_end,
        )
        for year, quarter, period_end, value in (
            (2024, 1, date(2024, 3, 31), "100"),
            (2024, 2, date(2024, 6, 30), "120"),
            (2024, 3, date(2024, 9, 30), "140"),
            (2025, 1, date(2025, 3, 31), "125"),
            (2025, 2, date(2025, 6, 30), "150"),
            (2025, 3, date(2025, 9, 30), "175"),
        )
    )

    result = year_over_year_growth_series(inputs)

    assert [point.observed_at for point in result.values] == [
        date(2025, 3, 31),
        date(2025, 6, 30),
        date(2025, 9, 30),
    ]
    assert [point.value for point in result.values] == [
        Decimal("25.00"),
        Decimal("25.00"),
        Decimal("25.00"),
    ]


def test_correlation_is_decimal_aligned_and_warns_against_causation() -> None:
    dates = (date(2025, 1, 1), date(2025, 2, 1), date(2025, 3, 1))
    left = tuple(
        observation(f"x{index}", str(index), observed_at=day)
        for index, day in enumerate(dates, start=1)
    )
    right = tuple(
        observation(f"y{index}", str(index * 2), unit="percent", observed_at=day)
        for index, day in enumerate(dates, start=1)
    )

    result = correlation(left, right)

    assert result.values[0].value == Decimal("1")
    assert result.unit == "coefficient"
    assert result.warnings == ("Correlation does not establish causation.",)


@pytest.mark.parametrize(
    "call, message",
    [
        (
            lambda: absolute_change(
                observation("usd", "1", unit="USD"),
                observation("percent", "1", unit="percent"),
            ),
            "Incompatible units",
        ),
        (
            lambda: percentage_change(observation("current", "1"), observation("missing", None)),
            "Missing observation values",
        ),
        (
            lambda: percentage_change(observation("current", "1"), observation("zero", "0")),
            "cannot be zero",
        ),
    ],
)
def test_calculations_fail_explicitly(call: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        call()


def test_chart_specification_is_provider_neutral_and_retains_lineage() -> None:
    dataset = ValidatedChartDataset(
        series=(ChartSeries(key="rate", label="Federal funds rate", unit="percent"),),
        points=(
            ChartPoint(
                x=date(2025, 1, 1),
                values={"rate": Decimal("4.33")},
                source_urls=(SOURCE,),
            ),
        ),
    )

    spec = generate_chart_specification(dataset, chart_type="line", title="Federal funds rate")

    assert spec.schema_version == "company-lens.chart.v1"
    assert spec.data == dataset.points
    assert spec.sources == (SOURCE,)


def test_chart_dataset_rejects_inconsistent_fields_and_missing_lineage() -> None:
    with pytest.raises(ValidationError, match="declared series"):
        ValidatedChartDataset(
            series=(ChartSeries(key="rate", label="Rate", unit="percent"),),
            points=(
                ChartPoint(
                    x=date(2025, 1, 1),
                    values={"other": Decimal("1")},
                    source_urls=(SOURCE,),
                ),
            ),
        )
    with pytest.raises(ValidationError, match="source lineage"):
        ValidatedChartDataset(
            series=(ChartSeries(key="rate", label="Rate", unit="percent"),),
            points=(
                ChartPoint(
                    x=date(2025, 1, 1),
                    values={"rate": Decimal("1")},
                    source_urls=(),
                ),
            ),
        )
