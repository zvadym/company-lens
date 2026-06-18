from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FredSeriesQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    series_ids: tuple[str, ...]
    observation_start: date | None = None
    observation_end: date | None = None
    include_missing: bool = False
    limit: int = Field(default=1000, ge=1, le=100_000)

    @model_validator(mode="after")
    def validate_query(self) -> FredSeriesQuery:
        if not self.series_ids:
            raise ValueError("At least one FRED series ID is required.")
        if (
            self.observation_start
            and self.observation_end
            and self.observation_start > self.observation_end
        ):
            raise ValueError("observation_start cannot be after observation_end.")
        return self


class FredSeriesMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    series_id: str
    title: str
    frequency: str
    frequency_short: str
    units: str
    units_short: str
    seasonal_adjustment: str
    seasonal_adjustment_short: str
    observation_start: date
    observation_end: date
    last_updated: datetime | None = None
    notes: str | None = None
    source_url: str


class FredObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID | None = None
    series_id: str
    observed_at: date
    realtime_start: date
    realtime_end: date
    value: Decimal | None
    raw_value: str
    is_missing: bool
    unit: str
    frequency: str
    source_url: str


class FredSeriesResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: FredSeriesQuery
    series: tuple[FredSeriesMetadata, ...]
    observations: tuple[FredObservation, ...]
    warnings: tuple[str, ...] = ()


class FredIngestionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID
    status: str
    series_seen: int
    observations_seen: int
    inserted: int
    updated: int
    missing: int
    failures: tuple[str, ...] = ()
