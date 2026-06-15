from __future__ import annotations

import os

from data_checks.http import build_client
from data_checks.models import CheckResult, FredSeriesConfig


FRED_SERIES_URL = "https://api.stlouisfed.org/fred/series"
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


def run_fred_checks(series: list[FredSeriesConfig]) -> list[CheckResult]:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        return [
            CheckResult(
                source="fred",
                check="credentials",
                status="skipped",
                message="FRED_API_KEY is not set; FRED checks were skipped.",
            )
        ]

    results: list[CheckResult] = []
    with build_client() as client:
        for item in series:
            results.append(_check_series_metadata(client, api_key, item))
            results.append(_check_series_observations(client, api_key, item))
    return results


def _check_series_metadata(client, api_key: str, item: FredSeriesConfig) -> CheckResult:
    params = {"api_key": api_key, "file_type": "json", "series_id": item.id}
    try:
        response = client.get(FRED_SERIES_URL, params=params)
        response.raise_for_status()
        payload = response.json()
        series = payload.get("seriess", [])
    except Exception as exc:
        return CheckResult(
            source="fred",
            check="series_metadata",
            status="failed",
            message=f"Could not load FRED metadata for {item.id}.",
            details={"series_id": item.id, "url": FRED_SERIES_URL, "error": repr(exc)},
        )

    if not series:
        return CheckResult(
            source="fred",
            check="series_metadata",
            status="failed",
            message=f"FRED series {item.id} was not found.",
            details={"series_id": item.id, "configured_name": item.name},
        )

    metadata = series[0]
    return CheckResult(
        source="fred",
        check="series_metadata",
        status="passed",
        message=f"FRED series {item.id} metadata found.",
        details={
            "series_id": item.id,
            "configured_name": item.name,
            "title": metadata.get("title"),
            "frequency": metadata.get("frequency"),
            "units": metadata.get("units"),
            "observation_start": metadata.get("observation_start"),
            "observation_end": metadata.get("observation_end"),
        },
    )


def _check_series_observations(client, api_key: str, item: FredSeriesConfig) -> CheckResult:
    params = {
        "api_key": api_key,
        "file_type": "json",
        "series_id": item.id,
        "sort_order": "desc",
        "limit": 1,
    }
    try:
        response = client.get(FRED_OBSERVATIONS_URL, params=params)
        response.raise_for_status()
        payload = response.json()
        observations = payload.get("observations", [])
    except Exception as exc:
        return CheckResult(
            source="fred",
            check="series_observations",
            status="failed",
            message=f"Could not load FRED observations for {item.id}.",
            details={"series_id": item.id, "url": FRED_OBSERVATIONS_URL, "error": repr(exc)},
        )

    if not observations:
        return CheckResult(
            source="fred",
            check="series_observations",
            status="failed",
            message=f"No observations returned for FRED series {item.id}.",
            details={"series_id": item.id},
        )

    latest = observations[0]
    status = "warning" if latest.get("value") == "." else "passed"
    return CheckResult(
        source="fred",
        check="series_observations",
        status=status,
        message=f"Latest FRED observation loaded for {item.id}.",
        details={
            "series_id": item.id,
            "date": latest.get("date"),
            "value": latest.get("value"),
        },
    )
