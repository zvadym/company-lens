from __future__ import annotations

import re
import unicodedata
import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from company_lens.db.models import (
    Company,
    CompanyAlias,
    CompanyIdentifier,
    CompanyTicker,
    SourceDocument,
)
from company_lens.retrieval.adaptive_schemas import (
    EntityCandidate,
    EntityResolution,
    ResolvedQuery,
)

ACCESSION_RE = re.compile(r"\b\d{10}-\d{2}-\d{6}\b")
CIK_RE = re.compile(r"(?<!\d)(?:CIK\s*[:#-]?\s*)?(\d{10})(?!\d)", re.IGNORECASE)
DATE_RE = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])-([0-2]\d|3[01])\b")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2}|2100)\b")
FORM_RE = re.compile(r"\b(10-K|10-Q|8-K|20-F|40-F|6-K|S-1)\b", re.IGNORECASE)
PERIOD_RE = re.compile(r"\b(FY|Q[1-4]|H[12])\b", re.IGNORECASE)

# Canonical metric names are deliberately provider-neutral. FinancialFact concepts remain
# source taxonomy values and are matched through aliases by StructuredFactRetriever.
METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "revenues", "sales", "net sales", "дохід", "виручка"),
    "net_income": ("net income", "net earnings", "profit", "чистий прибуток"),
    "operating_income": ("operating income", "operating profit", "операційний прибуток"),
    "total_assets": ("total assets", "assets", "активи"),
    "cash": ("cash and cash equivalents", "cash", "грошові кошти"),
    "free_cash_flow": ("free cash flow", "fcf", "вільний грошовий потік"),
    "employees": ("employees", "headcount", "працівники", "штат"),
}


class EntityResolver:
    """Resolve exact database entities before semantic retrieval is considered."""

    def __init__(self, *, session: Session) -> None:
        self._session = session

    def resolve(self, query: str) -> ResolvedQuery:
        cleaned = " ".join(query.strip().split())
        entities: list[EntityResolution] = []
        company_ids: list[uuid.UUID] = []

        company_entities = self._resolve_companies(cleaned)
        entities.extend(company_entities)
        for entity in company_entities:
            if entity.status == "resolved" and entity.candidates[0].id is not None:
                company_ids.append(entity.candidates[0].id)

        accessions = tuple(dict.fromkeys(ACCESSION_RE.findall(cleaned)))
        entities.extend(self._resolve_accessions(accessions))

        forms = tuple(dict.fromkeys(match.upper() for match in FORM_RE.findall(cleaned)))
        periods = tuple(dict.fromkeys(match.upper() for match in PERIOD_RE.findall(cleaned)))
        years = tuple(dict.fromkeys(int(value) for value in YEAR_RE.findall(cleaned)))
        dates = self._dates(cleaned)
        metrics = self._metrics(cleaned)

        entities.extend(
            EntityResolution(
                kind="filing_form",
                mention=form,
                status="resolved",
                canonical_value=form,
                candidates=(
                    EntityCandidate(
                        canonical_value=form,
                        display_value=form,
                        match_kind="exact_form",
                    ),
                ),
            )
            for form in forms
        )
        entities.extend(
            EntityResolution(
                kind="financial_metric",
                mention=metric,
                status="resolved",
                canonical_value=metric,
                candidates=(
                    EntityCandidate(
                        canonical_value=metric,
                        display_value=metric,
                        match_kind="metric_alias",
                    ),
                ),
            )
            for metric in metrics
        )

        return ResolvedQuery(
            query=cleaned,
            entities=tuple(entities),
            company_ids=tuple(dict.fromkeys(company_ids)),
            accession_numbers=accessions,
            filing_forms=forms,
            fiscal_years=years,
            fiscal_periods=periods,
            dates=dates,
            metrics=metrics,
        )

    def _resolve_companies(self, query: str) -> list[EntityResolution]:
        companies = self._session.scalars(select(Company).order_by(Company.id)).all()
        if not companies:
            return []
        company_by_id = {company.id: company for company in companies}
        labels: defaultdict[str, list[tuple[uuid.UUID, str]]] = defaultdict(list)
        for company in companies:
            for value, kind in (
                (company.legal_name, "legal_name"),
                (company.display_name, "display_name"),
                (company.cik, "cik"),
            ):
                if value:
                    labels[_normalize(value)].append((company.id, kind))
        for alias in self._session.scalars(select(CompanyAlias)).all():
            labels[_normalize(alias.alias)].append((alias.company_id, f"alias:{alias.kind.value}"))
        for ticker in self._session.scalars(select(CompanyTicker)).all():
            labels[_normalize(ticker.symbol)].append((ticker.company_id, "ticker"))
        for identifier in self._session.scalars(select(CompanyIdentifier)).all():
            labels[_normalize(identifier.value)].append(
                (identifier.company_id, f"identifier:{identifier.kind.value}")
            )

        normalized_query = f" {_normalize(query)} "
        matched_labels: list[str] = []
        for label in labels:
            if not label:
                continue
            if re.search(rf"(?<!\w){re.escape(label)}(?!\w)", normalized_query):
                matched_labels.append(label)

        # Prefer the longest phrase when one label is fully contained in another.
        selected: list[str] = []
        for label in sorted(matched_labels, key=lambda value: (-len(value), value)):
            if any(re.search(rf"(?<!\w){re.escape(label)}(?!\w)", longer) for longer in selected):
                continue
            selected.append(label)

        resolutions: list[EntityResolution] = []
        seen_company_sets: set[tuple[uuid.UUID, ...]] = set()
        for label in selected:
            matches = labels[label]
            ids = tuple(sorted({company_id for company_id, _ in matches}, key=str))
            if ids in seen_company_sets:
                continue
            seen_company_sets.add(ids)
            candidates = tuple(
                EntityCandidate(
                    id=company_id,
                    canonical_value=str(company_id),
                    display_value=company_by_id[company_id].display_name,
                    match_kind=next(
                        kind for candidate_id, kind in matches if candidate_id == company_id
                    ),
                )
                for company_id in ids
            )
            resolutions.append(
                EntityResolution(
                    kind="company",
                    mention=label,
                    status="resolved" if len(candidates) == 1 else "ambiguous",
                    canonical_value=str(ids[0]) if len(candidates) == 1 else None,
                    candidates=candidates,
                )
            )
        return resolutions

    def _resolve_accessions(self, accessions: tuple[str, ...]) -> list[EntityResolution]:
        if not accessions:
            return []
        documents = self._session.scalars(
            select(SourceDocument).where(SourceDocument.accession_number.in_(accessions))
        ).all()
        documents_by_accession = {document.accession_number: document for document in documents}
        resolutions: list[EntityResolution] = []
        for accession in accessions:
            document = documents_by_accession.get(accession)
            if document is None:
                resolutions.append(
                    EntityResolution(kind="filing", mention=accession, status="unresolved")
                )
                continue
            resolutions.append(
                EntityResolution(
                    kind="filing",
                    mention=accession,
                    status="resolved",
                    canonical_value=str(document.id),
                    candidates=(
                        EntityCandidate(
                            id=document.id,
                            canonical_value=str(document.id),
                            display_value=document.title or accession,
                            match_kind="accession_number",
                        ),
                    ),
                )
            )
        return resolutions

    @staticmethod
    def _dates(query: str) -> tuple[date, ...]:
        values: list[date] = []
        for year, month, day in DATE_RE.findall(query):
            try:
                values.append(date(int(year), int(month), int(day)))
            except ValueError:
                continue
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _metrics(query: str) -> tuple[str, ...]:
        normalized_query = f" {_normalize(query)} "
        matched: list[str] = []
        for canonical, aliases in METRIC_ALIASES.items():
            if any(
                re.search(rf"(?<!\w){re.escape(_normalize(alias))}(?!\w)", normalized_query)
                for alias in aliases
            ):
                matched.append(canonical)
        return tuple(matched)


def metric_aliases(metric: str) -> tuple[str, ...]:
    return METRIC_ALIASES.get(metric, (metric,))


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())
