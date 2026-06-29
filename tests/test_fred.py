from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from company_lens.db.base import Base
from company_lens.db.models import MacroObservation, MacroSeries
from company_lens.macro.client import FredClient, FredClientError
from company_lens.macro.schemas import FredSeriesQuery
from company_lens.macro.service import FredIngestionService, FredQueryService
from company_lens.macro.tool import build_langchain_fred_tool

FIXTURE = Path("tests/fixtures/fred/fedfunds.json")


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture
def fred_client() -> FredClient:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/series/observations"):
            return httpx.Response(200, json=payload["observations"])
        if request.url.path.endswith("/series"):
            return httpx.Response(200, json=payload["metadata"])
        return httpx.Response(404)

    with FredClient(api_key="test-key", transport=httpx.MockTransport(handler)) as client:
        yield client


def test_client_parses_metadata_values_and_missing_observations(
    fred_client: FredClient,
) -> None:
    metadata = fred_client.fetch_series("fedfunds")
    observations = fred_client.fetch_observations(metadata)

    assert metadata.series_id == "FEDFUNDS"
    assert metadata.units_short == "%"
    assert [item.value for item in observations] == [Decimal("4.33"), None, Decimal("4.33")]
    assert observations[1].is_missing is True
    assert all(item.source_url.endswith("/FEDFUNDS") for item in observations)


def test_client_errors_do_not_expose_api_key() -> None:
    secret = "do-not-leak-this-key"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error_message": "Bad request"})

    with (
        FredClient(
            api_key=secret,
            retry_attempts=1,
            transport=httpx.MockTransport(handler),
        ) as client,
        pytest.raises(FredClientError) as error,
    ):
        client.fetch_series("FEDFUNDS")

    assert secret not in str(error.value)
    assert "HTTP 400" in str(error.value)


def test_client_normalizes_api_key_before_request() -> None:
    seen_api_key: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_api_key.append(str(request.url.params["api_key"]))
        return httpx.Response(200, json={"seriess": []})

    with (
        FredClient(api_key="\n test-key \r", transport=httpx.MockTransport(handler)) as client,
        pytest.raises(FredClientError, match="no metadata"),
    ):
        client.fetch_series("FEDFUNDS")

    assert seen_api_key == ["test-key"]


def test_ingestion_is_idempotent_and_query_reads_cached_data(
    session: Session,
    fred_client: FredClient,
) -> None:
    service = FredIngestionService(session=session, client=fred_client)

    first = service.ingest(("FEDFUNDS",))
    second = service.ingest(("FEDFUNDS",))
    result = FredQueryService(session=session).query(
        FredSeriesQuery(
            series_ids=("FEDFUNDS",),
            observation_start=date(2025, 1, 1),
            observation_end=date(2025, 3, 1),
        )
    )

    assert first.inserted == 3
    assert first.missing == 1
    assert second.inserted == 0
    assert second.updated == 0
    assert len(session.scalars(select(MacroSeries)).all()) == 1
    assert len(session.scalars(select(MacroObservation)).all()) == 3
    assert [item.value for item in result.observations] == [
        Decimal("4.330000000000"),
        Decimal("4.330000000000"),
    ]
    assert result.warnings == ()


def test_query_can_explicitly_include_missing_values(
    session: Session,
    fred_client: FredClient,
) -> None:
    FredIngestionService(session=session, client=fred_client).ingest(("FEDFUNDS",))

    result = FredQueryService(session=session).query(
        FredSeriesQuery(series_ids=("FEDFUNDS",), include_missing=True)
    )

    assert len(result.observations) == 3
    assert result.observations[1].value is None
    assert result.observations[1].raw_value == "."


def test_query_without_date_range_limits_latest_observations(
    session: Session,
    fred_client: FredClient,
) -> None:
    FredIngestionService(session=session, client=fred_client).ingest(("FEDFUNDS",))

    result = FredQueryService(session=session).query(
        FredSeriesQuery(series_ids=("FEDFUNDS",), limit=1)
    )

    assert [item.observed_at for item in result.observations] == [date(2025, 3, 1)]
    assert [item.value for item in result.observations] == [Decimal("4.330000000000")]


def test_typed_tool_exposes_cached_fred_contract(session: Session) -> None:
    pytest.importorskip("langchain_core")
    tool = build_langchain_fred_tool(FredQueryService(session=session))

    result = tool.invoke({"series_ids": ["FEDFUNDS"]})

    assert tool.name == "query_fred_series"
    assert result["observations"] == []
    assert result["warnings"] == [
        "series_not_cached:FEDFUNDS",
        "no_matching_observations",
    ]
