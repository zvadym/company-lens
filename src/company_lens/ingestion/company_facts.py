from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from company_lens.config import Settings
from company_lens.db.models import (
    ArtifactKind,
    Company,
    CompanyIdentifier,
    CompanyTicker,
    DocumentKind,
    DocumentVersion,
    DocumentVersionState,
    Exchange,
    FinancialFact,
    IdentifierKind,
    IngestionFailure,
    IngestionRun,
    IngestionRunStatus,
    SourceArtifact,
    SourceDocument,
)
from company_lens.financials.mapping import (
    DEFAULT_MAPPING_PATH,
    MetricMapping,
    load_metric_mapping,
)
from company_lens.ingestion.artifacts import ArtifactStore
from company_lens.ingestion.sec_client import (
    SEC_COMPANY_FACTS_URL,
    SecClient,
    SecCompany,
    archive_base_url,
)
from company_lens.ingestion.sec_service import INITIAL_COMPANY_UNIVERSE

SEC_COMPANY_FACTS_SOURCE = "sec_company_facts"
SEC_TICKER_EXCHANGE_CODE = "SEC"


@dataclass(frozen=True)
class CompanyFactsIngestionOptions:
    tickers: tuple[str, ...]
    mapping_path: Path = DEFAULT_MAPPING_PATH


@dataclass(frozen=True)
class CompanyFactsIngestionResult:
    run_id: str
    status: str
    companies_seen: int
    facts_seen: int
    facts_inserted: int
    duplicates_skipped: int
    unmapped_concepts: int
    failures: int


@dataclass(frozen=True)
class ParsedFinancialFact:
    taxonomy: str
    concept: str
    canonical_metric: str
    label: str | None
    value: Decimal
    unit: str
    period_start: date | None
    period_end: date
    fiscal_year: int | None
    fiscal_period: str | None
    period_type: str
    form: str | None
    filed_date: date | None
    accession_number: str | None
    frame: str | None
    is_amendment: bool
    source_url: str
    source_hash: str


class CompanyFactsIngestionService:
    def __init__(
        self,
        *,
        session: Session,
        client: SecClient,
        artifact_store: ArtifactStore,
    ) -> None:
        self._session = session
        self._client = client
        self._artifact_store = artifact_store

    def ingest(self, options: CompanyFactsIngestionOptions) -> CompanyFactsIngestionResult:
        mapping = load_metric_mapping(options.mapping_path)
        run = IngestionRun(
            source_name=SEC_COMPANY_FACTS_SOURCE,
            status=IngestionRunStatus.STARTED,
            config_hash=_sha256(options.mapping_path.read_bytes()),
            parameters={
                "tickers": list(options.tickers),
                "mapping_version": mapping.version,
                "mapping_path": str(options.mapping_path),
            },
        )
        self._session.add(run)
        self._session.commit()

        companies_seen = 0
        facts_seen = 0
        facts_inserted = 0
        duplicates_skipped = 0
        unmapped_concepts = 0
        for ticker in options.tickers:
            try:
                company, sec_company = self._resolve_company(ticker)
                payload = self._client.fetch_company_facts(sec_company.cik)
                version = self._store_source(run, company, sec_company, payload, mapping)
                parsed, company_unmapped = parse_company_facts(
                    payload,
                    cik=sec_company.cik,
                    mapping=mapping,
                )
                inserted, duplicates = self._store_facts(
                    run=run,
                    company=company,
                    document_version=version,
                    mapping=mapping,
                    facts=parsed,
                )
                companies_seen += 1
                facts_seen += len(parsed)
                facts_inserted += inserted
                duplicates_skipped += duplicates
                unmapped_concepts += company_unmapped
                self._session.commit()
            except Exception as exc:
                self._session.rollback()
                self._session.add(
                    IngestionFailure(
                        run_id=run.id,
                        stage="company_facts",
                        message=str(exc),
                        details_json={"ticker": ticker},
                    )
                )
                self._session.commit()

        failures = len(
            self._session.scalars(
                select(IngestionFailure).where(IngestionFailure.run_id == run.id)
            ).all()
        )
        run.status = IngestionRunStatus.SUCCEEDED if failures == 0 else IngestionRunStatus.PARTIAL
        run.completed_at = datetime.now(UTC)
        run.parameters = {
            **run.parameters,
            "companies_seen": companies_seen,
            "facts_seen": facts_seen,
            "facts_inserted": facts_inserted,
            "duplicates_skipped": duplicates_skipped,
            "unmapped_concepts": unmapped_concepts,
            "failures": failures,
        }
        self._session.commit()
        return CompanyFactsIngestionResult(
            run_id=str(run.id),
            status="success" if failures == 0 else "partial_failed",
            companies_seen=companies_seen,
            facts_seen=facts_seen,
            facts_inserted=facts_inserted,
            duplicates_skipped=duplicates_skipped,
            unmapped_concepts=unmapped_concepts,
            failures=failures,
        )

    def _resolve_company(self, ticker: str) -> tuple[Company, SecCompany]:
        normalized = ticker.upper()
        existing = self._session.execute(
            select(Company, CompanyTicker)
            .join(CompanyTicker, CompanyTicker.company_id == Company.id)
            .where(CompanyTicker.symbol == normalized, CompanyTicker.valid_to.is_(None))
        ).first()
        if existing is not None and existing[0].cik:
            company = existing[0]
            return company, SecCompany(ticker=normalized, cik=company.cik, name=company.legal_name)

        resolved = self._client.resolve_ticker(normalized)
        company = self._session.scalar(select(Company).where(Company.cik == resolved.cik))
        if company is None:
            company = Company(
                legal_name=resolved.name,
                display_name=resolved.name,
                cik=resolved.cik,
            )
            self._session.add(company)
            self._session.flush()
        self._upsert_identifiers(company, resolved)
        self._session.flush()
        return company, resolved

    def _upsert_identifiers(self, company: Company, resolved: SecCompany) -> None:
        identifier = self._session.scalar(
            select(CompanyIdentifier).where(
                CompanyIdentifier.kind == IdentifierKind.CIK,
                CompanyIdentifier.value == resolved.cik,
            )
        )
        if identifier is None:
            self._session.add(
                CompanyIdentifier(
                    company_id=company.id,
                    kind=IdentifierKind.CIK,
                    value=resolved.cik,
                    source=SEC_COMPANY_FACTS_SOURCE,
                )
            )
        exchange = self._session.scalar(
            select(Exchange).where(Exchange.code == SEC_TICKER_EXCHANGE_CODE)
        )
        if exchange is None:
            exchange = Exchange(
                mic=SEC_TICKER_EXCHANGE_CODE,
                code=SEC_TICKER_EXCHANGE_CODE,
                name="SEC company ticker mapping",
                country_code="US",
            )
            self._session.add(exchange)
            self._session.flush()
        company_ticker = self._session.scalar(
            select(CompanyTicker).where(
                CompanyTicker.exchange_id == exchange.id,
                CompanyTicker.symbol == resolved.ticker,
                CompanyTicker.valid_from.is_(None),
            )
        )
        if company_ticker is None:
            self._session.add(
                CompanyTicker(
                    company_id=company.id,
                    exchange_id=exchange.id,
                    symbol=resolved.ticker,
                    is_primary=True,
                )
            )

    def _store_source(
        self,
        run: IngestionRun,
        company: Company,
        sec_company: SecCompany,
        payload: dict[str, Any],
        mapping: MetricMapping,
    ) -> DocumentVersion:
        source_url = SEC_COMPANY_FACTS_URL.format(cik=sec_company.cik.zfill(10))
        artifact_name = f"companyfacts-{_payload_hash(payload)[:16]}.json"
        artifact = self._artifact_store.store_json(
            relative_path=Path(sec_company.ticker) / artifact_name,
            payload=payload,
        )
        stable_source_id = f"CIK{sec_company.cik.zfill(10)}"
        document = self._session.scalar(
            select(SourceDocument).where(
                SourceDocument.source_system == SEC_COMPANY_FACTS_SOURCE,
                SourceDocument.stable_source_id == stable_source_id,
            )
        )
        if document is None:
            document = SourceDocument(
                company_id=company.id,
                kind=DocumentKind.SEC_COMPANY_FACTS,
                source_system=SEC_COMPANY_FACTS_SOURCE,
                stable_source_id=stable_source_id,
                source_url=source_url,
                title=f"{company.display_name} SEC Company Facts",
                metadata_json={"cik": sec_company.cik},
            )
            self._session.add(document)
            self._session.flush()
        version = self._session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.content_hash == artifact.content_hash,
            )
        )
        if version is not None:
            return version

        previous = self._session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.is_current.is_(True),
            )
        )
        if previous is not None:
            previous.is_current = False
            previous.state = DocumentVersionState.SUPERSEDED
        version = DocumentVersion(
            document_id=document.id,
            ingestion_run_id=run.id,
            version_label=f"{mapping.version}:{artifact.content_hash[:12]}",
            content_hash=artifact.content_hash,
            source_hash=artifact.content_hash,
            artifact_uri=str(artifact.path),
            state=DocumentVersionState.CURRENT,
            is_current=True,
            supersedes_version_id=previous.id if previous else None,
            metadata_json={"mapping_version": mapping.version},
        )
        self._session.add(version)
        self._session.flush()
        self._session.add(
            SourceArtifact(
                document_version_id=version.id,
                kind=ArtifactKind.OTHER,
                uri=str(artifact.path),
                content_hash=artifact.content_hash,
                mime_type=artifact.mime_type,
                byte_size=artifact.size_bytes,
            )
        )
        return version

    def _store_facts(
        self,
        *,
        run: IngestionRun,
        company: Company,
        document_version: DocumentVersion,
        mapping: MetricMapping,
        facts: Iterable[ParsedFinancialFact],
    ) -> tuple[int, int]:
        inserted = 0
        duplicates = 0
        for parsed in facts:
            existing = self._session.scalar(
                select(FinancialFact.id).where(FinancialFact.source_hash == parsed.source_hash)
            )
            if existing is not None:
                duplicates += 1
                continue
            self._session.add(
                FinancialFact(
                    company_id=company.id,
                    ingestion_run_id=run.id,
                    document_version_id=document_version.id,
                    taxonomy=parsed.taxonomy,
                    concept=parsed.concept,
                    canonical_metric=parsed.canonical_metric,
                    metric_mapping_version=mapping.version,
                    label=parsed.label,
                    value=parsed.value,
                    unit=parsed.unit,
                    period_start=parsed.period_start,
                    period_end=parsed.period_end,
                    fiscal_year=parsed.fiscal_year,
                    fiscal_period=parsed.fiscal_period,
                    period_type=parsed.period_type,
                    form=parsed.form,
                    filed_date=parsed.filed_date,
                    frame=parsed.frame,
                    is_amendment=parsed.is_amendment,
                    accession_number=parsed.accession_number,
                    dimensions={},
                    source_url=parsed.source_url,
                    source_hash=parsed.source_hash,
                )
            )
            inserted += 1
        return inserted, duplicates


def parse_company_facts(
    payload: dict[str, Any],
    *,
    cik: str,
    mapping: MetricMapping,
) -> tuple[list[ParsedFinancialFact], int]:
    raw_taxonomies = payload.get("facts")
    if not isinstance(raw_taxonomies, dict):
        raise ValueError("SEC Company Facts payload has no facts object.")
    parsed: list[ParsedFinancialFact] = []
    unmapped = 0
    for taxonomy, raw_concepts in raw_taxonomies.items():
        if not isinstance(raw_concepts, dict):
            continue
        for concept, concept_payload in raw_concepts.items():
            canonical_metric = mapping.resolve(
                cik=cik,
                taxonomy=str(taxonomy),
                concept=str(concept),
            )
            if canonical_metric is None:
                unmapped += 1
                continue
            if not isinstance(concept_payload, dict):
                continue
            label = _optional_string(concept_payload.get("label"))
            units = concept_payload.get("units")
            if not isinstance(units, dict):
                continue
            for unit, observations in units.items():
                if not isinstance(observations, list):
                    continue
                for raw in observations:
                    fact = _parse_fact(
                        raw,
                        cik=cik,
                        taxonomy=str(taxonomy),
                        concept=str(concept),
                        canonical_metric=canonical_metric,
                        label=label,
                        unit=str(unit),
                        mapping_version=mapping.version,
                    )
                    if fact is not None:
                        parsed.append(fact)
    return parsed, unmapped


def _parse_fact(
    raw: Any,
    *,
    cik: str,
    taxonomy: str,
    concept: str,
    canonical_metric: str,
    label: str | None,
    unit: str,
    mapping_version: str,
) -> ParsedFinancialFact | None:
    if not isinstance(raw, dict):
        return None
    period_end = _parse_date(raw.get("end"))
    if period_end is None or raw.get("val") is None:
        return None
    try:
        value = Decimal(str(raw["val"]))
    except (InvalidOperation, ValueError):
        return None
    period_start = _parse_date(raw.get("start"))
    form = _optional_string(raw.get("form"))
    accession = _optional_string(raw.get("accn"))
    fiscal_period = _optional_string(raw.get("fp"))
    frame = _optional_string(raw.get("frame"))
    filed_date = _parse_date(raw.get("filed"))
    fiscal_year = _optional_int(raw.get("fy"))
    period_type = classify_period(
        start=period_start,
        end=period_end,
        fiscal_period=fiscal_period,
    )
    source_url = (
        f"{archive_base_url(cik, accession)}/{accession}-index.html"
        if accession
        else SEC_COMPANY_FACTS_URL.format(cik=cik.zfill(10))
    )
    identity = {
        "cik": cik.zfill(10),
        "taxonomy": taxonomy,
        "concept": concept,
        "canonical_metric": canonical_metric,
        "mapping_version": mapping_version,
        "unit": unit,
        "value": str(value),
        "start": period_start.isoformat() if period_start else None,
        "end": period_end.isoformat(),
        "fy": fiscal_year,
        "fp": fiscal_period,
        "form": form,
        "filed": filed_date.isoformat() if filed_date else None,
        "accn": accession,
        "frame": frame,
    }
    return ParsedFinancialFact(
        taxonomy=taxonomy,
        concept=concept,
        canonical_metric=canonical_metric,
        label=label,
        value=value,
        unit=unit,
        period_start=period_start,
        period_end=period_end,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        period_type=period_type,
        form=form,
        filed_date=filed_date,
        accession_number=accession,
        frame=frame,
        is_amendment=bool(form and form.upper().endswith("/A")),
        source_url=source_url,
        source_hash=_sha256(json.dumps(identity, sort_keys=True).encode("utf-8")),
    )


def classify_period(*, start: date | None, end: date, fiscal_period: str | None) -> str:
    if start is None:
        return "instant"
    duration_days = (end - start).days + 1
    if duration_days >= 300:
        return "annual"
    if 70 <= duration_days <= 110:
        return "quarter"
    if fiscal_period and fiscal_period.upper() in {"Q2", "Q3", "Q4"} and duration_days < 300:
        return "year_to_date"
    return "other"


def build_company_facts_options(
    *,
    tickers: tuple[str, ...],
    all_companies: bool,
    mapping_path: Path = DEFAULT_MAPPING_PATH,
) -> CompanyFactsIngestionOptions:
    selected = tuple(INITIAL_COMPANY_UNIVERSE) if all_companies else tickers
    if not selected:
        raise ValueError("Specify at least one --ticker or use --all.")
    return CompanyFactsIngestionOptions(
        tickers=tuple(dict.fromkeys(ticker.upper() for ticker in selected)),
        mapping_path=mapping_path,
    )


def build_company_facts_client(settings: Settings) -> SecClient:
    if not settings.sec_user_agent:
        raise ValueError("COMPANY_LENS_SEC_USER_AGENT must be configured.")
    return SecClient(
        settings.sec_user_agent,
        timeout_seconds=settings.sec_request_timeout_seconds,
        retry_attempts=settings.sec_retry_attempts,
        rate_limit_per_second=settings.sec_rate_limit_per_second,
        max_response_bytes=settings.sec_max_response_bytes,
    )


def _payload_hash(payload: dict[str, Any]) -> str:
    return _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _optional_string(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
