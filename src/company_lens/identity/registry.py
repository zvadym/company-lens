from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from company_lens.db.models import (
    Company,
    CompanyIdentity,
    CompanyIdentityAlias,
    CompanyIdentityTicker,
)
from company_lens.identity.curated import CuratedIdentity
from company_lens.ingestion.sec_client import SecCompany

CIK_MENTION_RE = re.compile(r"^(?:CIK\s*[:#-]?\s*)?(\d{1,10})$", re.IGNORECASE)


@dataclass(frozen=True)
class CompanyIdentityCandidate:
    identity_id: uuid.UUID
    company_id: uuid.UUID | None
    cik: str | None
    display_name: str
    legal_name: str
    primary_ticker: str | None
    match_kind: str


@dataclass(frozen=True)
class CompanyIdentityResolution:
    mention: str
    status: str
    candidates: tuple[CompanyIdentityCandidate, ...] = ()

    @property
    def resolved(self) -> CompanyIdentityCandidate | None:
        return self.candidates[0] if self.status == "resolved" else None


class CompanyIdentityRegistry:
    def __init__(self, *, session: Session) -> None:
        self._session = session

    def seed_curated_identities(self, identities: Iterable[CuratedIdentity]) -> None:
        for item in identities:
            identity = self.upsert_identity(
                cik=item.cik,
                legal_name=item.legal_name,
                display_name=item.display_name,
                source=item.source,
            )
            for index, ticker in enumerate(item.tickers):
                self.upsert_ticker(
                    identity,
                    ticker,
                    source=item.source,
                    is_primary=index == 0,
                )
            for alias in item.aliases:
                self.upsert_alias(
                    identity,
                    alias.alias,
                    kind=alias.kind,
                    source=item.source,
                    confidence=alias.confidence,
                )

    def hydrate_sec_ticker_map(self, ticker_map: Mapping[str, SecCompany]) -> None:
        seen_ciks: set[str] = set()
        for company in ticker_map.values():
            cik = company.cik.zfill(10)
            identity = self.upsert_identity(
                cik=cik,
                legal_name=company.name,
                display_name=company.name,
                source="sec_edgar",
            )
            self.upsert_ticker(identity, company.ticker, source="sec_edgar", is_primary=True)
            self.upsert_alias(identity, company.name, kind="legal", source="sec_edgar")
            seen_ciks.add(cik)
        if seen_ciks:
            self._session.flush()

    def upsert_identity(
        self,
        *,
        cik: str | None,
        legal_name: str,
        display_name: str,
        source: str,
        company_id: uuid.UUID | None = None,
        confidence: Decimal | None = None,
        source_metadata: dict[str, object] | None = None,
    ) -> CompanyIdentity:
        normalized_cik = cik.zfill(10) if cik else None
        linked_company_id = company_id or self._local_company_id(normalized_cik)
        identity = self._identity_by_cik(normalized_cik)
        if identity is None and linked_company_id is not None:
            identity = self._session.scalar(
                select(CompanyIdentity).where(CompanyIdentity.company_id == linked_company_id)
            )
        if identity is None:
            identity = CompanyIdentity(
                company_id=linked_company_id,
                cik=normalized_cik,
                legal_name=legal_name,
                normalized_legal_name=normalize_company_name(legal_name),
                display_name=display_name,
                normalized_display_name=normalize_company_name(display_name),
                source=source,
                confidence=confidence,
                source_metadata=source_metadata or {},
            )
            self._session.add(identity)
        else:
            identity.company_id = identity.company_id or linked_company_id
            identity.cik = identity.cik or normalized_cik
            identity.legal_name = legal_name
            identity.normalized_legal_name = normalize_company_name(legal_name)
            identity.display_name = display_name
            identity.normalized_display_name = normalize_company_name(display_name)
            identity.source = source
            identity.confidence = confidence
            identity.source_metadata = source_metadata or identity.source_metadata or {}
        self._session.flush()
        return identity

    def upsert_ticker(
        self,
        identity: CompanyIdentity,
        symbol: str,
        *,
        source: str,
        is_primary: bool = False,
        exchange_code: str | None = None,
        source_metadata: dict[str, object] | None = None,
    ) -> CompanyIdentityTicker:
        normalized = normalize_ticker(symbol)
        ticker = self._session.scalar(
            select(CompanyIdentityTicker).where(
                CompanyIdentityTicker.identity_id == identity.id,
                CompanyIdentityTicker.normalized_symbol == normalized,
                CompanyIdentityTicker.source == source,
                CompanyIdentityTicker.valid_from.is_(None),
            )
        )
        if ticker is None:
            ticker = CompanyIdentityTicker(
                identity_id=identity.id,
                symbol=symbol.strip().upper().removeprefix("$"),
                normalized_symbol=normalized,
                exchange_code=exchange_code,
                is_primary=is_primary,
                source=source,
                source_metadata=source_metadata or {},
            )
            self._session.add(ticker)
        else:
            ticker.symbol = symbol.strip().upper().removeprefix("$")
            ticker.exchange_code = exchange_code
            ticker.is_primary = ticker.is_primary or is_primary
            ticker.source_metadata = source_metadata or ticker.source_metadata or {}
        self._session.flush()
        return ticker

    def upsert_alias(
        self,
        identity: CompanyIdentity,
        alias: str,
        *,
        kind: str,
        source: str,
        confidence: Decimal | None = None,
        source_metadata: dict[str, object] | None = None,
    ) -> CompanyIdentityAlias:
        normalized = normalize_company_name(alias)
        row = self._session.scalar(
            select(CompanyIdentityAlias).where(
                CompanyIdentityAlias.identity_id == identity.id,
                CompanyIdentityAlias.normalized_alias == normalized,
                CompanyIdentityAlias.kind == kind,
                CompanyIdentityAlias.source == source,
            )
        )
        if row is None:
            row = CompanyIdentityAlias(
                identity_id=identity.id,
                alias=alias.strip(),
                normalized_alias=normalized,
                kind=kind,
                source=source,
                confidence=confidence,
                source_metadata=source_metadata or {},
            )
            self._session.add(row)
        else:
            row.alias = alias.strip()
            row.confidence = confidence
            row.source_metadata = source_metadata or row.source_metadata or {}
        self._session.flush()
        return row

    def resolve_mention(self, mention: str) -> CompanyIdentityResolution:
        cleaned = " ".join(mention.split())
        if not cleaned:
            return CompanyIdentityResolution(mention=mention, status="unresolved")
        cik = _cik(cleaned)
        if cik is not None:
            candidates = self._candidates_for_identities(self._by_cik(cik), "cik")
            return _resolution(cleaned, candidates)

        ticker_candidates = self._candidates_for_identities(
            self._by_ticker(cleaned),
            "ticker",
        )
        if ticker_candidates:
            return _resolution(cleaned, ticker_candidates)

        normalized = normalize_company_name(cleaned)
        alias_candidates = self._candidates_for_identities(
            self._by_alias(normalized),
            "alias",
        )
        if alias_candidates:
            return _resolution(cleaned, alias_candidates)

        name_candidates = self._candidates_for_identities(
            self._by_name(normalized),
            "company_name",
        )
        return _resolution(cleaned, name_candidates)

    def _local_company_id(self, cik: str | None) -> uuid.UUID | None:
        if cik is None:
            return None
        return self._session.scalar(select(Company.id).where(Company.cik == cik))

    def _identity_by_cik(self, cik: str | None) -> CompanyIdentity | None:
        if cik is None:
            return None
        return self._session.scalar(select(CompanyIdentity).where(CompanyIdentity.cik == cik))

    def _by_cik(self, cik: str) -> tuple[CompanyIdentity, ...]:
        return tuple(
            self._session.scalars(_identity_select().where(CompanyIdentity.cik == cik)).all()
        )

    def _by_ticker(self, mention: str) -> tuple[CompanyIdentity, ...]:
        normalized = normalize_ticker(mention)
        if not normalized or " " in normalized:
            return ()
        return tuple(
            self._session.scalars(
                _identity_select()
                .join(CompanyIdentityTicker)
                .where(CompanyIdentityTicker.normalized_symbol == normalized)
                .order_by(CompanyIdentity.display_name, CompanyIdentity.id)
            ).all()
        )

    def _by_alias(self, normalized: str) -> tuple[CompanyIdentity, ...]:
        if not normalized:
            return ()
        return tuple(
            self._session.scalars(
                _identity_select()
                .join(CompanyIdentityAlias)
                .where(CompanyIdentityAlias.normalized_alias == normalized)
                .order_by(CompanyIdentity.display_name, CompanyIdentity.id)
            ).all()
        )

    def _by_name(self, normalized: str) -> tuple[CompanyIdentity, ...]:
        if not normalized:
            return ()
        return tuple(
            self._session.scalars(
                _identity_select()
                .where(
                    (CompanyIdentity.normalized_display_name == normalized)
                    | (CompanyIdentity.normalized_legal_name == normalized)
                )
                .order_by(CompanyIdentity.display_name, CompanyIdentity.id)
            ).all()
        )

    @staticmethod
    def _candidates_for_identities(
        identities: Iterable[CompanyIdentity],
        match_kind: str,
    ) -> tuple[CompanyIdentityCandidate, ...]:
        seen: set[uuid.UUID] = set()
        candidates: list[CompanyIdentityCandidate] = []
        for identity in identities:
            if identity.id in seen:
                continue
            seen.add(identity.id)
            candidates.append(
                CompanyIdentityCandidate(
                    identity_id=identity.id,
                    company_id=identity.company_id,
                    cik=identity.cik,
                    display_name=identity.display_name,
                    legal_name=identity.legal_name,
                    primary_ticker=_primary_ticker(identity),
                    match_kind=match_kind,
                )
            )
        return tuple(candidates)


def normalize_company_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def normalize_ticker(value: str) -> str:
    return value.strip().upper().removeprefix("$")


def _identity_select() -> Select[tuple[CompanyIdentity]]:
    return select(CompanyIdentity).options(
        selectinload(CompanyIdentity.tickers),
        selectinload(CompanyIdentity.aliases),
    )


def _primary_ticker(identity: CompanyIdentity) -> str | None:
    tickers = sorted(
        identity.tickers,
        key=lambda ticker: (not ticker.is_primary, ticker.symbol),
    )
    return tickers[0].symbol if tickers else None


def _cik(value: str) -> str | None:
    match = CIK_MENTION_RE.match(value)
    if match is None:
        return None
    return match.group(1).zfill(10)


def _resolution(
    mention: str,
    candidates: tuple[CompanyIdentityCandidate, ...],
) -> CompanyIdentityResolution:
    if not candidates:
        return CompanyIdentityResolution(mention=mention, status="unresolved")
    if len(candidates) == 1:
        return CompanyIdentityResolution(mention=mention, status="resolved", candidates=candidates)
    return CompanyIdentityResolution(mention=mention, status="ambiguous", candidates=candidates)
