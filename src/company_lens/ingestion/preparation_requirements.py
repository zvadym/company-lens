from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

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


@dataclass(frozen=True)
class CompanyDataPreparationRequirements:
    financial_facts: bool = False
    documents: bool = False

    @property
    def any(self) -> bool:
        return self.financial_facts or self.documents


def company_data_is_ready(
    *,
    financial_fact_count: int,
    indexed_chunk_count: int,
    requirements: CompanyDataPreparationRequirements,
) -> bool:
    return (not requirements.financial_facts or financial_fact_count > 0) and (
        not requirements.documents or indexed_chunk_count > 0
    )


def requested_tickers(
    session_factory: sessionmaker[Session],
    *,
    tickers: tuple[str, ...],
    company_ids: tuple[uuid.UUID, ...],
) -> tuple[str, ...]:
    selected = [ticker.strip().upper() for ticker in tickers if ticker.strip()]
    if company_ids:
        with session_factory() as session:
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


def ready_tickers(
    session_factory: sessionmaker[Session],
    tickers: tuple[str, ...],
    *,
    requirements: CompanyDataPreparationRequirements,
    index_name: str,
    index_version: str,
) -> tuple[str, ...]:
    ready: list[str] = []
    with session_factory() as session:
        for ticker in tickers:
            company = company_for_ticker(session, ticker)
            if company is None:
                continue
            fact_count = financial_fact_count(session, company.id)
            chunk_count = indexed_chunk_count(
                session,
                company.id,
                index_name=index_name,
                index_version=index_version,
            )
            if company_data_is_ready(
                financial_fact_count=fact_count,
                indexed_chunk_count=chunk_count,
                requirements=requirements,
            ):
                ready.append(ticker)
    return tuple(ready)


def current_sec_document_version_ids(
    session_factory: sessionmaker[Session],
    tickers: tuple[str, ...],
) -> tuple[uuid.UUID, ...]:
    company_ids: list[uuid.UUID] = []
    with session_factory() as session:
        for ticker in tickers:
            company = company_for_ticker(session, ticker)
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


def company_for_ticker(session: Session, ticker: str) -> Company | None:
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


def indexed_chunk_count(
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


def financial_fact_count(session: Session, company_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count(FinancialFact.id)).where(FinancialFact.company_id == company_id)
        )
        or 0
    )
