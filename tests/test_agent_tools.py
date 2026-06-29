from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from company_lens.agent.schemas import (
    AgentErrorCategory,
    AgentErrorSeverity,
    CompanyMentionCandidate,
)
from company_lens.agent.tools import ResearchToolError, SqlResearchTools
from company_lens.config import Settings
from company_lens.db.models import Base
from company_lens.ingestion.sec_client import SecCompany
from company_lens.macro.schemas import FredObservation, FredSeriesMetadata, FredSeriesQuery
from company_lens.retrieval.adaptive_schemas import ResolvedQuery


class _FakeSecClient:
    def __init__(self, ticker_map: dict[str, SecCompany]) -> None:
        self._ticker_map = ticker_map

    def __enter__(self) -> _FakeSecClient:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def fetch_ticker_map(self) -> dict[str, SecCompany]:
        return self._ticker_map


def _sql_tools_with_sec_map(
    monkeypatch: pytest.MonkeyPatch,
    ticker_map: dict[str, SecCompany],
) -> SqlResearchTools:
    monkeypatch.setattr(
        "company_lens.agent.tools.build_sec_client_from_settings",
        lambda settings: _FakeSecClient(ticker_map),
    )
    return SqlResearchTools(
        session_factory=sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:")),
        settings=Settings(sec_user_agent="company-lens-test contact@example.com"),
    )


def test_sql_research_tools_owns_a_distinct_session_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions: list[Session] = []

    class TrackingResolver:
        def __init__(self, *, session: Session) -> None:
            sessions.append(session)

        def resolve(self, query: str, *, include_companies: bool = True) -> ResolvedQuery:
            return ResolvedQuery(query=query)

    monkeypatch.setattr("company_lens.agent.tools.EntityResolver", TrackingResolver)
    factory = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:"))
    tools = SqlResearchTools(session_factory=factory)

    tools.resolve_entities("first")
    tools.resolve_entities("second")

    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]


def test_sql_research_tools_sanitizes_unexpected_service_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenResolver:
        def __init__(self, *, session: Session) -> None:
            pass

        def resolve(self, query: str, *, include_companies: bool = True) -> Any:
            raise RuntimeError("database failed with sk-secret-value")

    monkeypatch.setattr("company_lens.agent.tools.EntityResolver", BrokenResolver)
    factory = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:"))
    tools = SqlResearchTools(session_factory=factory)

    with pytest.raises(ResearchToolError) as captured:
        tools.resolve_entities("query")

    assert captured.value.error.category is AgentErrorCategory.TOOL
    assert captured.value.error.severity is AgentErrorSeverity.RECOVERABLE
    assert "sk-secret-value" not in str(captured.value)


def test_sql_research_tools_discovers_public_company_from_sec_ticker_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyResolver:
        def __init__(self, *, session: Session) -> None:
            pass

        def resolve(self, query: str, *, include_companies: bool = True) -> ResolvedQuery:
            return ResolvedQuery(query=query)

    class FakeSecClient:
        def __enter__(self) -> FakeSecClient:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def fetch_ticker_map(self) -> dict[str, SecCompany]:
            return {
                "NFLX": SecCompany(
                    ticker="NFLX",
                    cik="0001065280",
                    name="NETFLIX INC",
                )
            }

    monkeypatch.setattr("company_lens.agent.tools.EntityResolver", EmptyResolver)
    monkeypatch.setattr(
        "company_lens.agent.tools.build_sec_client_from_settings",
        lambda settings: FakeSecClient(),
    )
    factory = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:"))
    tools = SqlResearchTools(
        session_factory=factory,
        settings=Settings(sec_user_agent="company-lens-test contact@example.com"),
    )

    resolved = tools.resolve_entities("What risks did Netflix report?")

    assert len(resolved.entities) == 1
    entity = resolved.entities[0]
    assert entity.kind == "public_company"
    assert entity.status == "unresolved"
    assert entity.candidates[0].canonical_value == "NFLX"


def test_sql_research_tools_resolves_extracted_public_company_brand_from_sec_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyResolver:
        def __init__(self, *, session: Session) -> None:
            pass

        def resolve(self, query: str, *, include_companies: bool = True) -> ResolvedQuery:
            return ResolvedQuery(query=query)

    class FakeSecClient:
        def __enter__(self) -> FakeSecClient:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def fetch_ticker_map(self) -> dict[str, SecCompany]:
            return {
                "ZM": SecCompany(
                    ticker="ZM",
                    cik="0001585521",
                    name="Zoom Communications Inc.",
                )
            }

    monkeypatch.setattr("company_lens.agent.tools.EntityResolver", EmptyResolver)
    monkeypatch.setattr(
        "company_lens.agent.tools.build_sec_client_from_settings",
        lambda settings: FakeSecClient(),
    )
    factory = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:"))
    tools = SqlResearchTools(
        session_factory=factory,
        settings=Settings(sec_user_agent="company-lens-test contact@example.com"),
    )

    entities = tools.resolve_public_company_mentions((CompanyMentionCandidate(mention="Zoom"),))

    assert len(entities) == 1
    assert entities[0].mention == "Zoom"
    assert entities[0].candidates[0].canonical_value == "ZM"


def test_sql_research_tools_verifies_llm_alias_candidate_ticker_with_sec_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSecClient:
        def __enter__(self) -> FakeSecClient:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def fetch_ticker_map(self) -> dict[str, SecCompany]:
            return {
                "GOOG": SecCompany(
                    ticker="GOOG",
                    cik="0001652044",
                    name="Alphabet Inc.",
                )
            }

    monkeypatch.setattr(
        "company_lens.agent.tools.build_sec_client_from_settings",
        lambda settings: FakeSecClient(),
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = sessionmaker(bind=engine)
    tools = SqlResearchTools(
        session_factory=factory,
        settings=Settings(sec_user_agent="company-lens-test contact@example.com"),
    )

    entities = tools.resolve_public_company_mentions(
        (
            CompanyMentionCandidate(
                mention="Google",
                ticker="GOOG",
                legal_name="Alphabet Inc.",
            ),
        )
    )

    assert len(entities) == 1
    assert entities[0].mention == "Google"
    assert entities[0].kind == "public_company"
    assert entities[0].candidates[0].canonical_value == "GOOG"


def test_sql_research_tools_prefers_clear_name_over_conflicting_ticker_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _sql_tools_with_sec_map(
        monkeypatch,
        {
            "NET": SecCompany(
                ticker="NET",
                cik="0001477333",
                name="Cloudflare, Inc.",
            ),
            "NCLH": SecCompany(
                ticker="NCLH",
                cik="0001513761",
                name="Norwegian Cruise Line Holdings Ltd.",
            ),
        },
    )

    entities = tools.resolve_public_company_mentions(
        (CompanyMentionCandidate(mention="Cloudflare", ticker="NCLH"),)
    )

    assert len(entities) == 1
    assert entities[0].status == "unresolved"
    assert entities[0].candidates[0].canonical_value == "NET"


def test_sql_research_tools_prefers_clear_name_when_ticker_hint_has_legal_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _sql_tools_with_sec_map(
        monkeypatch,
        {
            "NET": SecCompany(
                ticker="NET",
                cik="0001477333",
                name="Cloudflare, Inc.",
            ),
            "NCLH": SecCompany(
                ticker="NCLH",
                cik="0001513761",
                name="Norwegian Cruise Line Holdings Ltd.",
            ),
        },
    )

    entities = tools.resolve_public_company_mentions(
        (
            CompanyMentionCandidate(
                mention="Cloudflare",
                ticker="NCLH",
                legal_name="Norwegian Cruise Line Holdings Ltd.",
            ),
        )
    )

    assert len(entities) == 1
    assert entities[0].status == "unresolved"
    assert entities[0].candidates[0].canonical_value == "NET"


def test_sql_research_tools_prefers_clear_name_over_conflicting_cik_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _sql_tools_with_sec_map(
        monkeypatch,
        {
            "NET": SecCompany(
                ticker="NET",
                cik="0001477333",
                name="Cloudflare, Inc.",
            ),
            "MDT": SecCompany(
                ticker="MDT",
                cik="0000064670",
                name="Medtronic plc",
            ),
        },
    )

    entities = tools.resolve_public_company_mentions(
        (
            CompanyMentionCandidate(
                mention="Cloudflare",
                ticker="MDT",
                cik="0000064670",
                legal_name="Medtronic plc",
            ),
        )
    )

    assert len(entities) == 1
    assert entities[0].status == "unresolved"
    assert entities[0].candidates[0].canonical_value == "NET"


def test_sql_research_tools_returns_ambiguous_sec_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _sql_tools_with_sec_map(
        monkeypatch,
        {
            "ACMA": SecCompany(
                ticker="ACMA",
                cik="0000000001",
                name="Acme Holdings Inc.",
            ),
            "ACMB": SecCompany(
                ticker="ACMB",
                cik="0000000002",
                name="Acme Software Inc.",
            ),
        },
    )

    entities = tools.resolve_public_company_mentions((CompanyMentionCandidate(mention="Acme"),))

    assert len(entities) == 1
    assert entities[0].status == "ambiguous"
    assert [candidate.canonical_value for candidate in entities[0].candidates] == [
        "ACMA",
        "ACMB",
    ]


def test_sql_research_tools_resolves_specific_legal_name_above_prefix_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _sql_tools_with_sec_map(
        monkeypatch,
        {
            "ACMA": SecCompany(
                ticker="ACMA",
                cik="0000000001",
                name="Acme Holdings Inc.",
            ),
            "ACMB": SecCompany(
                ticker="ACMB",
                cik="0000000002",
                name="Acme Software Inc.",
            ),
        },
    )

    entities = tools.resolve_public_company_mentions(
        (
            CompanyMentionCandidate(
                mention="Acme Holdings Inc.",
                legal_name="Acme Holdings Inc.",
            ),
        )
    )

    assert len(entities) == 1
    assert entities[0].status == "unresolved"
    assert entities[0].candidates[0].canonical_value == "ACMA"
    assert entities[0].candidates[0].match_kind == "sec_legal_name_extracted"


def test_sql_research_tools_keeps_ambiguous_prefix_even_with_llm_ticker_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _sql_tools_with_sec_map(
        monkeypatch,
        {
            "BNO": SecCompany(
                ticker="BNO",
                cik="0001472494",
                name="United States Brent Oil Fund LP",
            ),
            "UAL": SecCompany(
                ticker="UAL",
                cik="0000100517",
                name="United Airlines Holdings Inc.",
            ),
        },
    )

    entities = tools.resolve_public_company_mentions(
        (
            CompanyMentionCandidate(
                mention="United",
                ticker="BNO",
                legal_name="United States Brent Oil Fund LP",
            ),
        )
    )

    assert len(entities) == 1
    assert entities[0].status == "ambiguous"
    assert [candidate.canonical_value for candidate in entities[0].candidates] == [
        "UAL",
        "BNO",
    ]


def test_sql_research_tools_blocks_common_chart_word_as_plain_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _sql_tools_with_sec_map(
        monkeypatch,
        {
            "BAR": SecCompany(
                ticker="BAR",
                cik="0001690437",
                name="GraniteShares Gold Trust",
            )
        },
    )

    assert tools.resolve_public_company_mentions((CompanyMentionCandidate(mention="bar"),)) == ()
    assert (
        tools.resolve_public_company_mentions(
            (CompanyMentionCandidate(mention="bar", ticker="BAR"),)
        )
        == ()
    )

    entities = tools.resolve_public_company_mentions((CompanyMentionCandidate(mention="$BAR"),))
    assert len(entities) == 1
    assert entities[0].candidates[0].canonical_value == "BAR"


def test_sql_research_tools_ingests_missing_fred_series_on_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeFredClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> FakeFredClient:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def fetch_series(self, series_id: str) -> FredSeriesMetadata:
            assert series_id == "FEDFUNDS"
            return FredSeriesMetadata(
                series_id="FEDFUNDS",
                title="Federal Funds Effective Rate",
                frequency="Monthly",
                frequency_short="M",
                units="Percent",
                units_short="%",
                seasonal_adjustment="Not Seasonally Adjusted",
                seasonal_adjustment_short="NSA",
                observation_start=date(2025, 1, 1),
                observation_end=date(2025, 1, 1),
                source_url="https://fred.stlouisfed.org/series/FEDFUNDS",
            )

        def fetch_observations(
            self,
            metadata: FredSeriesMetadata,
            *,
            observation_start: date | None = None,
            observation_end: date | None = None,
        ) -> tuple[FredObservation, ...]:
            assert metadata.series_id == "FEDFUNDS"
            assert observation_start is None
            assert observation_end is None
            return (
                FredObservation(
                    series_id="FEDFUNDS",
                    observed_at=date(2025, 1, 1),
                    realtime_start=date(2025, 2, 1),
                    realtime_end=date(2025, 2, 1),
                    value=Decimal("4.33"),
                    raw_value="4.33",
                    is_missing=False,
                    unit="%",
                    frequency="M",
                    source_url="https://fred.stlouisfed.org/series/FEDFUNDS",
                ),
            )

    monkeypatch.setattr("company_lens.agent.tools.FredClient", FakeFredClient)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    tools = SqlResearchTools(
        session_factory=sessionmaker(bind=engine),
        settings=Settings(fred_api_key="test-key"),
    )

    result = tools.query_macro_series(FredSeriesQuery(series_ids=("FEDFUNDS",)))

    assert result.warnings == ()
    assert [item.value for item in result.observations] == [Decimal("4.330000000000")]
