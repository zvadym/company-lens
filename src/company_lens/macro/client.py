from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from company_lens.macro.schemas import FredObservation, FredSeriesMetadata

FRED_SERIES_PAGE = "https://fred.stlouisfed.org/series/{series_id}"
QueryParameter = str | int | float | bool | None


class FredClientError(RuntimeError):
    pass


class FredClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.stlouisfed.org/fred",
        timeout_seconds: float = 30.0,
        retry_attempts: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("A non-empty FRED API key is required.")
        self._api_key = api_key
        self._retry_attempts = retry_attempts
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    def __enter__(self) -> FredClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_series(self, series_id: str) -> FredSeriesMetadata:
        normalized = series_id.strip().upper()
        payload = self._get("/series", {"series_id": normalized})
        rows = payload.get("seriess")
        if not isinstance(rows, list) or not rows:
            raise FredClientError(f"FRED returned no metadata for series {normalized}.")
        row = _mapping(rows[0], f"metadata for {normalized}")
        source_url = FRED_SERIES_PAGE.format(series_id=normalized)
        return FredSeriesMetadata(
            series_id=str(row["id"]),
            title=str(row["title"]),
            frequency=str(row["frequency"]),
            frequency_short=str(row["frequency_short"]),
            units=str(row["units"]),
            units_short=str(row["units_short"]),
            seasonal_adjustment=str(row["seasonal_adjustment"]),
            seasonal_adjustment_short=str(row["seasonal_adjustment_short"]),
            observation_start=date.fromisoformat(str(row["observation_start"])),
            observation_end=date.fromisoformat(str(row["observation_end"])),
            last_updated=_optional_datetime(row.get("last_updated")),
            notes=str(row["notes"]) if row.get("notes") else None,
            source_url=source_url,
        )

    def fetch_observations(
        self,
        metadata: FredSeriesMetadata,
        *,
        observation_start: date | None = None,
        observation_end: date | None = None,
    ) -> tuple[FredObservation, ...]:
        params: dict[str, QueryParameter] = {"series_id": metadata.series_id}
        if observation_start:
            params["observation_start"] = observation_start.isoformat()
        if observation_end:
            params["observation_end"] = observation_end.isoformat()
        payload = self._get("/series/observations", params)
        rows = payload.get("observations")
        if not isinstance(rows, list):
            raise FredClientError(f"FRED returned invalid observations for {metadata.series_id}.")
        observations: list[FredObservation] = []
        for item in rows:
            row = _mapping(item, f"observation for {metadata.series_id}")
            raw_value = str(row.get("value", "."))
            is_missing = raw_value in {"", ".", "NaN", "nan"}
            observations.append(
                FredObservation(
                    series_id=metadata.series_id,
                    observed_at=date.fromisoformat(str(row["date"])),
                    realtime_start=date.fromisoformat(str(row["realtime_start"])),
                    realtime_end=date.fromisoformat(str(row["realtime_end"])),
                    value=None if is_missing else Decimal(raw_value),
                    raw_value=raw_value,
                    is_missing=is_missing,
                    unit=metadata.units_short,
                    frequency=metadata.frequency_short,
                    source_url=metadata.source_url,
                )
            )
        return tuple(observations)

    def _get(self, path: str, params: Mapping[str, QueryParameter]) -> dict[str, Any]:
        request_params = {**params, "api_key": self._api_key, "file_type": "json"}
        last_error: Exception | None = None
        for attempt in range(self._retry_attempts):
            try:
                response = self._client.get(path, params=request_params)
                if response.status_code >= 500 and attempt + 1 < self._retry_attempts:
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise FredClientError("FRED response must be a JSON object.")
                return payload
            except httpx.HTTPStatusError as exc:
                last_error = FredClientError(f"FRED returned HTTP {exc.response.status_code}.")
                if attempt + 1 >= self._retry_attempts:
                    break
            except httpx.HTTPError as exc:
                last_error = FredClientError(f"FRED transport error: {type(exc).__name__}.")
                if attempt + 1 >= self._retry_attempts:
                    break
            except (ValueError, FredClientError) as exc:
                last_error = exc
                if attempt + 1 >= self._retry_attempts:
                    break
        raise FredClientError(f"FRED request failed: {last_error}") from last_error


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FredClientError(f"FRED returned invalid {context}.")
    return value


def _optional_datetime(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace(" ", "T"))
