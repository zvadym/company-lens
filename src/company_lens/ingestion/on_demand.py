from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from company_lens.config import Settings
from company_lens.db.models import (
    ChunkEmbedding,
    Company,
    CompanyTicker,
    DocumentChunk,
    DocumentKind,
    DocumentVersion,
    EmbeddingIndex,
    FinancialFact,
    SourceDocument,
)
from company_lens.ingestion.artifacts import ArtifactStore
from company_lens.ingestion.company_facts import (
    CompanyFactsIngestionService,
    build_company_facts_client,
    build_company_facts_options,
)
from company_lens.ingestion.sec_service import (
    DEFAULT_FORMS,
    SecIngestionService,
    build_default_options,
    build_sec_client_from_settings,
)
from company_lens.processing.service import DocumentProcessingOptions, DocumentProcessingService
from company_lens.retrieval.embeddings import Embedder
from company_lens.retrieval.indexing import EmbeddingIndexingService
from company_lens.retrieval.schemas import EmbeddingIndexingRequest


@dataclass(frozen=True)
class CompanyDataPreparationResult:
    status: str
    requested_tickers: tuple[str, ...]
    skipped_tickers: tuple[str, ...]
    prepared_tickers: tuple[str, ...]
    companies_seen: int = 0
    filings_seen: int = 0
    facts_seen: int = 0
    documents_processed: int = 0
    chunks_indexed: int = 0
    failures: int = 0


class OnDemandCompanyDataPreparer:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        embedder: Embedder | None,
        index_name: str,
        index_version: str,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._embedder = embedder
        self._index_name = index_name
        self._index_version = index_version

    def prepare(
        self,
        *,
        tickers: tuple[str, ...] = (),
        company_ids: tuple[uuid.UUID, ...] = (),
    ) -> CompanyDataPreparationResult:
        requested = self._requested_tickers(tickers=tickers, company_ids=company_ids)
        if not requested:
            return CompanyDataPreparationResult(
                status="skipped",
                requested_tickers=(),
                skipped_tickers=(),
                prepared_tickers=(),
            )

        ready = self._ready_tickers(requested)
        pending = tuple(ticker for ticker in requested if ticker not in ready)
        if not pending:
            return CompanyDataPreparationResult(
                status="skipped",
                requested_tickers=requested,
                skipped_tickers=requested,
                prepared_tickers=(),
            )

        companies_seen = 0
        filings_seen = 0
        facts_seen = 0
        failures = 0
        artifact_store = ArtifactStore(self._settings.sec_artifact_root)
        with self._session_factory() as session:
            try:
                options = build_default_options(
                    tickers=pending,
                    all_companies=False,
                    forms=DEFAULT_FORMS,
                    settings=self._settings,
                    download_exhibits=False,
                )
                with build_sec_client_from_settings(self._settings) as client:
                    result = SecIngestionService(
                        session=session,
                        client=client,
                        artifact_store=artifact_store,
                    ).ingest(options)
                companies_seen += result.companies_seen
                filings_seen += result.filings_seen
                failures += result.failures
            except Exception:
                failures += len(pending)

        with self._session_factory() as session:
            try:
                facts_options = build_company_facts_options(
                    tickers=pending,
                    all_companies=False,
                )
                with build_company_facts_client(self._settings) as client:
                    facts_result = CompanyFactsIngestionService(
                        session=session,
                        client=client,
                        artifact_store=artifact_store,
                    ).ingest(facts_options)
                facts_seen += facts_result.facts_seen
                failures += facts_result.failures
            except Exception:
                failures += len(pending)

        document_version_ids = self._document_version_ids(pending)
        documents_processed = 0
        chunks_indexed = 0
        if document_version_ids:
            with self._session_factory() as session:
                process_result = DocumentProcessingService(session=session).process(
                    DocumentProcessingOptions(document_version_ids=document_version_ids)
                )
                documents_processed = process_result.documents_processed
            with self._session_factory() as session:
                index_result = EmbeddingIndexingService(
                    session=session,
                    embedder=self._embedder,
                ).index_chunks(
                    EmbeddingIndexingRequest(
                        index_name=self._index_name,
                        index_version=self._index_version,
                        document_version_ids=document_version_ids,
                    )
                )
                chunks_indexed = index_result.indexed
                failures += index_result.failed

        return CompanyDataPreparationResult(
            status="success" if failures == 0 else "partial_failed",
            requested_tickers=requested,
            skipped_tickers=ready,
            prepared_tickers=pending,
            companies_seen=companies_seen,
            filings_seen=filings_seen,
            facts_seen=facts_seen,
            documents_processed=documents_processed,
            chunks_indexed=chunks_indexed,
            failures=failures,
        )

    def _requested_tickers(
        self,
        *,
        tickers: tuple[str, ...],
        company_ids: tuple[uuid.UUID, ...],
    ) -> tuple[str, ...]:
        selected = [ticker.upper() for ticker in tickers if ticker.strip()]
        if company_ids:
            with self._session_factory() as session:
                rows = session.scalars(
                    select(CompanyTicker.symbol)
                    .where(
                        CompanyTicker.company_id.in_(company_ids),
                        CompanyTicker.is_primary.is_(True),
                        CompanyTicker.valid_to.is_(None),
                    )
                    .order_by(CompanyTicker.symbol)
                ).all()
            selected.extend(symbol.upper() for symbol in rows)
        return tuple(dict.fromkeys(selected))

    def _ready_tickers(self, tickers: tuple[str, ...]) -> tuple[str, ...]:
        ready: list[str] = []
        with self._session_factory() as session:
            for ticker in tickers:
                company = _company_for_ticker(session, ticker)
                if company is None:
                    continue
                if (
                    _indexed_chunk_count(
                        session,
                        company.id,
                        index_name=self._index_name,
                        index_version=self._index_version,
                    )
                    > 0
                    and _financial_fact_count(session, company.id) > 0
                ):
                    ready.append(ticker)
        return tuple(ready)

    def _document_version_ids(self, tickers: tuple[str, ...]) -> tuple[uuid.UUID, ...]:
        company_ids: list[uuid.UUID] = []
        with self._session_factory() as session:
            for ticker in tickers:
                company = _company_for_ticker(session, ticker)
                if company is not None:
                    company_ids.append(company.id)
            if not company_ids:
                return ()
            return tuple(
                session.scalars(
                    select(DocumentVersion.id)
                    .join(SourceDocument, SourceDocument.id == DocumentVersion.document_id)
                    .where(
                        SourceDocument.company_id.in_(company_ids),
                        SourceDocument.kind == DocumentKind.SEC_FILING,
                        DocumentVersion.is_current.is_(True),
                    )
                    .order_by(SourceDocument.filing_date.desc(), SourceDocument.id)
                ).all()
            )


def _company_for_ticker(session: Session, ticker: str) -> Company | None:
    return session.scalar(
        select(Company)
        .join(CompanyTicker, CompanyTicker.company_id == Company.id)
        .where(
            CompanyTicker.symbol == ticker.upper(),
            CompanyTicker.is_primary.is_(True),
            CompanyTicker.valid_to.is_(None),
        )
        .order_by(Company.display_name)
    )


def _indexed_chunk_count(
    session: Session,
    company_id: uuid.UUID,
    *,
    index_name: str,
    index_version: str,
) -> int:
    return (
        session.scalar(
            select(func.count(DocumentChunk.id))
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
            .join(SourceDocument, SourceDocument.id == DocumentVersion.document_id)
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
            .join(EmbeddingIndex, EmbeddingIndex.id == ChunkEmbedding.embedding_index_id)
            .where(
                SourceDocument.company_id == company_id,
                EmbeddingIndex.name == index_name,
                EmbeddingIndex.index_version == index_version,
            )
        )
        or 0
    )


def _financial_fact_count(session: Session, company_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count(FinancialFact.id)).where(FinancialFact.company_id == company_id)
        )
        or 0
    )
