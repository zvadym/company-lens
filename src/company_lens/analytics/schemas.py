from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, model_validator


class NumericObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    value: Decimal | None
    unit: str
    source_url: str
    observed_at: date | None = None


class CalculationPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    value: Decimal
    observed_at: date | None = None


class CalculationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: str
    values: tuple[CalculationPoint, ...]
    inputs: tuple[NumericObservation, ...]
    formula: str
    unit: str
    sources: tuple[str, ...]
    precision: str = "decimal:28-significant-digits"
    warnings: tuple[str, ...] = ()


class ChartSeries(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    unit: str


class ChartPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: date
    values: dict[str, Decimal]
    source_urls: tuple[str, ...]


class ValidatedChartDataset(BaseModel):
    model_config = ConfigDict(frozen=True)

    series: tuple[ChartSeries, ...]
    points: tuple[ChartPoint, ...]

    @model_validator(mode="after")
    def validate_dataset(self) -> ValidatedChartDataset:
        if not self.series:
            raise ValueError("A chart dataset requires at least one series.")
        if not self.points:
            raise ValueError("A chart dataset requires at least one point.")
        keys = [item.key for item in self.series]
        if len(keys) != len(set(keys)):
            raise ValueError("Chart series keys must be unique.")
        if any(
            not item.key.strip() or not item.label.strip() or not item.unit.strip()
            for item in self.series
        ):
            raise ValueError("Chart fields, labels, and units must be non-empty.")
        expected = set(keys)
        for point in self.points:
            if set(point.values) != expected:
                raise ValueError("Every chart point must contain exactly the declared series.")
            if not point.source_urls:
                raise ValueError("Every chart point must retain source lineage.")
        dates = [point.x for point in self.points]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise ValueError("Chart points must have unique ascending dates.")
        return self


class ChartSpecification(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = "company-lens.chart.v1"
    chart_type: str
    title: str
    x_label: str
    series: tuple[ChartSeries, ...]
    data: tuple[ChartPoint, ...]
    sources: tuple[str, ...]
