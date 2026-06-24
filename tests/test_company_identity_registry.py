from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from company_lens.db.base import Base
from company_lens.db.models import Company, CompanyIdentity, CompanyIdentityAlias
from company_lens.identity import CompanyIdentityRegistry, load_curated_identities
from company_lens.ingestion.sec_client import SecCompany
from company_lens.retrieval.resolution import EntityResolver


def test_curated_google_alias_resolves_to_persisted_alphabet_identity(
    session: Session,
) -> None:
    registry = CompanyIdentityRegistry(session=session)

    registry.seed_curated_identities(load_curated_identities())
    session.commit()

    resolved = registry.resolve_mention("Google")

    assert resolved.status == "resolved"
    assert resolved.resolved is not None
    assert resolved.resolved.display_name == "Alphabet Inc."
    assert resolved.resolved.cik == "0001652044"
    assert resolved.resolved.primary_ticker == "GOOG"
    assert resolved.resolved.match_kind == "alias"
    assert session.scalar(select(CompanyIdentity).where(CompanyIdentity.cik == "0001652044"))
    assert session.scalar(
        select(CompanyIdentityAlias).where(CompanyIdentityAlias.normalized_alias == "google")
    )


def test_sec_ticker_map_hydration_links_identity_to_existing_local_company(
    session: Session,
) -> None:
    company = Company(
        legal_name="Netflix, Inc.",
        display_name="Netflix",
        cik="0001065280",
    )
    session.add(company)
    session.flush()
    registry = CompanyIdentityRegistry(session=session)

    registry.hydrate_sec_ticker_map(
        {
            "NFLX": SecCompany(
                ticker="NFLX",
                cik="0001065280",
                name="NETFLIX INC",
            )
        }
    )
    session.commit()

    resolved = registry.resolve_mention("$NFLX")

    assert resolved.status == "resolved"
    assert resolved.resolved is not None
    assert resolved.resolved.company_id == company.id
    assert resolved.resolved.primary_ticker == "NFLX"
    assert registry.resolve_mention("NETFLIX INC").status == "resolved"


def test_shared_alias_returns_ambiguity_instead_of_guessing(session: Session) -> None:
    registry = CompanyIdentityRegistry(session=session)
    first = registry.upsert_identity(
        cik="0000000001",
        legal_name="Acme Software Inc.",
        display_name="Acme Software",
        source="fixture",
    )
    second = registry.upsert_identity(
        cik="0000000002",
        legal_name="Acme Hardware Inc.",
        display_name="Acme Hardware",
        source="fixture",
    )
    registry.upsert_alias(first, "Acme", kind="common", source="fixture")
    registry.upsert_alias(second, "Acme", kind="common", source="fixture")
    session.commit()

    resolved = registry.resolve_mention("Acme")

    assert resolved.status == "ambiguous"
    assert {candidate.display_name for candidate in resolved.candidates} == {
        "Acme Software",
        "Acme Hardware",
    }


def test_unknown_identity_is_unresolved(session: Session) -> None:
    resolved = CompanyIdentityRegistry(session=session).resolve_mention("Definitely Unknown Co")

    assert resolved.status == "unresolved"
    assert resolved.candidates == ()


def test_entity_resolver_exposes_curated_identity_as_public_company_for_on_demand_prepare(
    session: Session,
) -> None:
    CompanyIdentityRegistry(session=session).seed_curated_identities(load_curated_identities())
    session.commit()

    resolved = EntityResolver(session=session).resolve("а тепер те саме для google revenue")

    public_company = next(entity for entity in resolved.entities if entity.kind == "public_company")
    assert public_company.mention == "google"
    assert public_company.status == "unresolved"
    assert public_company.candidates[0].canonical_value == "GOOG"
    assert public_company.candidates[0].display_value == "Alphabet Inc."
    assert resolved.company_ids == ()
    assert resolved.metrics == ("revenue",)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
