from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from company_lens.db.models import (
    IngestionRun,
    IngestionRunStatus,
    MacroObservation,
    MacroSeries,
)
from company_lens.macro.client import FredClient
from company_lens.macro.schemas import (
    FredIngestionResult,
    FredObservation,
    FredSeriesMetadata,
    FredSeriesQuery,
    FredSeriesResult,
)

FRED_SOURCE = "fred"


class FredIngestionService:
    def __init__(self, *, session: Session, client: FredClient) -> None:
        self._session = session
        self._client = client

    def ingest(
        self,
        series_ids: tuple[str, ...],
        *,
        observation_start: date | None = None,
        observation_end: date | None = None,
    ) -> FredIngestionResult:
        normalized = tuple(
            dict.fromkeys(item.strip().upper() for item in series_ids if item.strip())
        )
        if not normalized:
            raise ValueError("At least one FRED series ID is required.")
        if observation_start and observation_end and observation_start > observation_end:
            raise ValueError("observation_start cannot be after observation_end.")
        run = IngestionRun(
            source_name=FRED_SOURCE,
            status=IngestionRunStatus.STARTED,
            parameters={
                "series_ids": list(normalized),
                "observation_start": observation_start.isoformat() if observation_start else None,
                "observation_end": observation_end.isoformat() if observation_end else None,
            },
        )
        self._session.add(run)
        self._session.commit()

        seen = inserted = updated = missing = 0
        failures: list[str] = []
        for series_id in normalized:
            try:
                metadata = self._client.fetch_series(series_id)
                self._upsert_series(metadata)
                observations = self._client.fetch_observations(
                    metadata,
                    observation_start=observation_start,
                    observation_end=observation_end,
                )
                seen += len(observations)
                missing += sum(item.is_missing for item in observations)
                series_inserted, series_updated = self._store_observations(run, observations)
                inserted += series_inserted
                updated += series_updated
                self._session.commit()
            except Exception as exc:
                self._session.rollback()
                failures.append(f"{series_id}: {exc}")

        run.status = IngestionRunStatus.SUCCEEDED if not failures else IngestionRunStatus.PARTIAL
        run.completed_at = datetime.now(UTC)
        run.parameters = {
            **run.parameters,
            "observations_seen": seen,
            "inserted": inserted,
            "updated": updated,
            "missing": missing,
            "failures": failures,
        }
        self._session.commit()
        return FredIngestionResult(
            run_id=run.id,
            status="success" if not failures else "partial_failed",
            series_seen=len(normalized) - len(failures),
            observations_seen=seen,
            inserted=inserted,
            updated=updated,
            missing=missing,
            failures=tuple(failures),
        )

    def _upsert_series(self, item: FredSeriesMetadata) -> None:
        row = self._session.get(MacroSeries, item.series_id)
        values = {
            "title": item.title,
            "frequency": item.frequency,
            "frequency_short": item.frequency_short,
            "units": item.units,
            "units_short": item.units_short,
            "seasonal_adjustment": item.seasonal_adjustment,
            "seasonal_adjustment_short": item.seasonal_adjustment_short,
            "observation_start": item.observation_start,
            "observation_end": item.observation_end,
            "last_updated_at_source": item.last_updated,
            "notes": item.notes,
            "source_url": item.source_url,
        }
        if row is None:
            self._session.add(MacroSeries(series_id=item.series_id, **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self._session.flush()

    def _store_observations(
        self,
        run: IngestionRun,
        observations: tuple[FredObservation, ...],
    ) -> tuple[int, int]:
        inserted = updated = 0
        for item in observations:
            row = self._session.scalar(
                select(MacroObservation).where(
                    MacroObservation.series_id == item.series_id,
                    MacroObservation.observed_at == item.observed_at,
                    MacroObservation.realtime_start == item.realtime_start,
                    MacroObservation.realtime_end == item.realtime_end,
                )
            )
            source_hash = _source_hash(item)
            if row is None:
                self._session.add(
                    MacroObservation(
                        ingestion_run_id=run.id,
                        series_id=item.series_id,
                        source_name=FRED_SOURCE,
                        observed_at=item.observed_at,
                        vintage_date=item.realtime_end,
                        realtime_start=item.realtime_start,
                        realtime_end=item.realtime_end,
                        value=item.value,
                        raw_value=item.raw_value,
                        is_missing=item.is_missing,
                        unit=item.unit,
                        frequency=item.frequency,
                        source_url=item.source_url,
                        source_hash=source_hash,
                    )
                )
                inserted += 1
            elif row.source_hash != source_hash:
                row.ingestion_run_id = run.id
                row.value = item.value
                row.raw_value = item.raw_value
                row.is_missing = item.is_missing
                row.unit = item.unit
                row.frequency = item.frequency
                row.source_url = item.source_url
                row.source_hash = source_hash
                updated += 1
        return inserted, updated


class FredQueryService:
    def __init__(self, *, session: Session) -> None:
        self._session = session

    def query(self, request: FredSeriesQuery) -> FredSeriesResult:
        normalized = tuple(item.strip().upper() for item in request.series_ids)
        series_rows = self._session.scalars(
            select(MacroSeries)
            .where(MacroSeries.series_id.in_(normalized))
            .order_by(MacroSeries.series_id)
        ).all()
        statement = (
            select(MacroObservation)
            .where(MacroObservation.series_id.in_(normalized))
            .order_by(MacroObservation.series_id, MacroObservation.observed_at)
            .limit(request.limit)
        )
        if request.observation_start:
            statement = statement.where(MacroObservation.observed_at >= request.observation_start)
        if request.observation_end:
            statement = statement.where(MacroObservation.observed_at <= request.observation_end)
        if not request.include_missing:
            statement = statement.where(MacroObservation.is_missing.is_(False))
        rows = self._session.scalars(statement).all()
        warnings: list[str] = []
        missing_series = sorted(set(normalized) - {row.series_id for row in series_rows})
        if missing_series:
            warnings.append("series_not_cached:" + ",".join(missing_series))
        if not rows:
            warnings.append("no_matching_observations")
        return FredSeriesResult(
            query=request,
            series=tuple(_metadata(row) for row in series_rows),
            observations=tuple(_observation(row) for row in rows),
            warnings=tuple(warnings),
        )


def _source_hash(item: FredObservation) -> str:
    raw = "|".join(
        (
            item.series_id,
            item.observed_at.isoformat(),
            item.realtime_start.isoformat(),
            item.realtime_end.isoformat(),
            item.raw_value,
            item.unit,
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _metadata(row: MacroSeries) -> FredSeriesMetadata:
    return FredSeriesMetadata(
        series_id=row.series_id,
        title=row.title,
        frequency=row.frequency,
        frequency_short=row.frequency_short,
        units=row.units,
        units_short=row.units_short,
        seasonal_adjustment=row.seasonal_adjustment,
        seasonal_adjustment_short=row.seasonal_adjustment_short,
        observation_start=row.observation_start,
        observation_end=row.observation_end,
        last_updated=row.last_updated_at_source,
        notes=row.notes,
        source_url=row.source_url,
    )


def _observation(row: MacroObservation) -> FredObservation:
    return FredObservation(
        id=row.id,
        series_id=row.series_id,
        observed_at=row.observed_at,
        realtime_start=row.realtime_start,
        realtime_end=row.realtime_end,
        value=row.value,
        raw_value=row.raw_value,
        is_missing=row.is_missing,
        unit=row.unit,
        frequency=row.frequency,
        source_url=row.source_url,
    )
