from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PeriodType = Literal["instant", "quarter", "year_to_date", "annual", "other"]


class FinancialFactQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_ids: tuple[uuid.UUID, ...] = ()
    tickers: tuple[str, ...] = ()
    metrics: tuple[str, ...]
    period_start: date | None = None
    period_end: date | None = None
    fiscal_years: tuple[int, ...] = ()
    fiscal_periods: tuple[str, ...] = ()
    period_types: tuple[PeriodType, ...] = ()
    units: tuple[str, ...] = ()
    include_amendments: bool = True
    limit: int = Field(default=200, ge=1, le=2000)

    @model_validator(mode="after")
    def validate_query(self) -> FinancialFactQuery:
        if not self.metrics:
            raise ValueError("At least one canonical metric is required.")
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start cannot be after period_end.")
        return self


class FinancialFactObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    ticker: str | None
    metric: str
    value: Decimal
    unit: str
    period_start: date | None
    period_end: date
    period_type: PeriodType
    fiscal_year: int | None
    fiscal_period: str | None
    form: str | None
    filed_date: date | None
    accession_number: str | None
    taxonomy: str
    concept: str
    frame: str | None
    is_amendment: bool
    has_conflict: bool
    mapping_version: str
    source_url: str


class FinancialFactQueryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: FinancialFactQuery
    observations: tuple[FinancialFactObservation, ...]
    available_units: tuple[str, ...]
    warnings: tuple[str, ...] = ()
