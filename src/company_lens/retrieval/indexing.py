from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from company_lens.db.models import (
    ChunkEmbedding,
    Company,
    DocumentChunk,
    DocumentVersion,
    EmbeddingIndex,
    SourceDocument,
)
from company_lens.observability.telemetry import bind_embedding_observation
from company_lens.retrieval.embeddings import Embedder, LocalFeatureHashingEmbedder
from company_lens.retrieval.schemas import (
    EmbeddingFailure,
    EmbeddingIndexingRequest,
    EmbeddingIndexingResult,
)


@dataclass(frozen=True)
class _ChunkEmbeddingContext:
    company_id: uuid.UUID | None
    company_name: str | None
    cik: str | None
    tickers: tuple[str, ...]
    source_document_id: uuid.UUID | None
    document_version_id: uuid.UUID


class EmbeddingIndexingService:
    def __init__(
        self,
        *,
        session: Session,
        embedder: Embedder | None = None,
    ) -> None:
        self._session = session
        self._embedder = embedder or LocalFeatureHashingEmbedder()

    def index_chunks(self, request: EmbeddingIndexingRequest) -> EmbeddingIndexingResult:
        embedding_index = self._get_or_create_index(request)
        chunks = self._chunks_to_consider(request)

        indexed = 0
        skipped = 0
        stale_rebuilt = 0
        failures: list[EmbeddingFailure] = []

        for batch_start in range(0, len(chunks), request.batch_size):
            batch = chunks[batch_start : batch_start + request.batch_size]
            pending: list[tuple[DocumentChunk, ChunkEmbedding | None]] = []
            for chunk in batch:
                existing = self._session.scalar(
                    select(ChunkEmbedding).where(
                        ChunkEmbedding.chunk_id == chunk.id,
                        ChunkEmbedding.embedding_index_id == embedding_index.id,
                    )
                )
                if (
                    existing is not None
                    and existing.content_hash == chunk.content_hash
                    and not request.force
                ):
                    skipped += 1
                    continue
                pending.append((chunk, existing))

            embedded: list[tuple[DocumentChunk, ChunkEmbedding | None, list[float]]] = []
            batch_failures: list[EmbeddingFailure] = []
            for company_pending in self._pending_by_company(pending):
                group_embedded, group_failures = self._embed_with_isolation(
                    company_pending,
                    request=request,
                    embedding_index=embedding_index,
                )
                embedded.extend(group_embedded)
                batch_failures.extend(group_failures)
            failures.extend(batch_failures)
            try:
                batch_indexed = 0
                batch_stale_rebuilt = 0
                for chunk, existing, vector in embedded:
                    if existing is not None:
                        self._session.delete(existing)
                        self._session.flush()
                        if existing.content_hash != chunk.content_hash:
                            batch_stale_rebuilt += 1
                    self._session.add(
                        ChunkEmbedding(
                            chunk_id=chunk.id,
                            embedding_index_id=embedding_index.id,
                            embedding=vector,
                            content_hash=chunk.content_hash,
                        )
                    )
                    batch_indexed += 1
                self._session.commit()
                indexed += batch_indexed
                stale_rebuilt += batch_stale_rebuilt
            except Exception as exc:
                self._session.rollback()
                failures.extend(
                    EmbeddingFailure(
                        chunk_id=chunk.id,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                    for chunk, _existing, _vector in embedded
                )

        return EmbeddingIndexingResult(
            index_id=embedding_index.id,
            index_name=embedding_index.name,
            index_version=embedding_index.index_version,
            embedding_model=embedding_index.embedding_model,
            dimensions=embedding_index.dimensions,
            indexed=indexed,
            skipped=skipped,
            stale_rebuilt=stale_rebuilt,
            failed=len(failures),
            failures=tuple(failures),
        )

    def _embed_with_isolation(
        self,
        pending: list[tuple[DocumentChunk, ChunkEmbedding | None]],
        *,
        request: EmbeddingIndexingRequest,
        embedding_index: EmbeddingIndex,
    ) -> tuple[
        list[tuple[DocumentChunk, ChunkEmbedding | None, list[float]]],
        list[EmbeddingFailure],
    ]:
        if not pending:
            return [], []
        try:
            with bind_embedding_observation(
                metadata=self._embedding_metadata(
                    pending,
                    request=request,
                    embedding_index=embedding_index,
                ),
                tags=_embedding_tags(self._embedder.provider),
            ):
                vectors = self._embedder.embed_texts([chunk.text for chunk, _ in pending])
            return [
                (chunk, existing, vector)
                for (chunk, existing), vector in zip(pending, vectors, strict=True)
            ], []
        except Exception as exc:
            if len(pending) == 1:
                chunk, _existing = pending[0]
                return [], [
                    EmbeddingFailure(
                        chunk_id=chunk.id,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                ]
            midpoint = len(pending) // 2
            left_embedded, left_failures = self._embed_with_isolation(
                pending[:midpoint],
                request=request,
                embedding_index=embedding_index,
            )
            right_embedded, right_failures = self._embed_with_isolation(
                pending[midpoint:],
                request=request,
                embedding_index=embedding_index,
            )
            return left_embedded + right_embedded, left_failures + right_failures

    def _get_or_create_index(self, request: EmbeddingIndexingRequest) -> EmbeddingIndex:
        embedding_index = self._session.scalar(
            select(EmbeddingIndex).where(
                EmbeddingIndex.name == request.index_name,
                EmbeddingIndex.index_version == request.index_version,
            )
        )
        if embedding_index is not None:
            if (
                embedding_index.embedding_model != self._embedder.model_name
                or embedding_index.dimensions != self._embedder.dimensions
            ):
                raise ValueError(
                    "Embedding index version already exists with a different model or dimensions."
                )
            return embedding_index

        embedding_index = EmbeddingIndex(
            name=request.index_name,
            index_version=request.index_version,
            embedding_model=self._embedder.model_name,
            dimensions=self._embedder.dimensions,
            distance_metric="cosine",
            metadata_json={"provider": self._embedder.provider},
        )
        self._session.add(embedding_index)
        self._session.commit()
        return embedding_index

    def _chunks_to_consider(self, request: EmbeddingIndexingRequest) -> list[DocumentChunk]:
        statement = select(DocumentChunk).order_by(DocumentChunk.created_at, DocumentChunk.id)
        if request.document_version_ids:
            statement = statement.where(
                DocumentChunk.document_version_id.in_(request.document_version_ids)
            )
        if request.limit is not None:
            statement = statement.limit(request.limit)
        return list(self._session.scalars(statement).all())

    def _pending_by_company(
        self,
        pending: list[tuple[DocumentChunk, ChunkEmbedding | None]],
    ) -> list[list[tuple[DocumentChunk, ChunkEmbedding | None]]]:
        groups: dict[uuid.UUID | None, list[tuple[DocumentChunk, ChunkEmbedding | None]]] = {}
        for item in pending:
            context = self._chunk_context(item[0])
            groups.setdefault(context.company_id, []).append(item)
        return list(groups.values())

    def _embedding_metadata(
        self,
        pending: list[tuple[DocumentChunk, ChunkEmbedding | None]],
        *,
        request: EmbeddingIndexingRequest,
        embedding_index: EmbeddingIndex,
    ) -> dict[str, object]:
        contexts = [self._chunk_context(chunk) for chunk, _existing in pending]
        company_ids = {context.company_id for context in contexts if context.company_id is not None}
        company_names = sorted(
            {
                context.company_name
                for context in contexts
                if context.company_name is not None and context.company_name
            }
        )
        tickers = sorted({ticker for context in contexts for ticker in context.tickers})
        source_document_ids = sorted(
            {
                str(context.source_document_id)
                for context in contexts
                if context.source_document_id is not None
            }
        )
        document_version_ids = sorted({str(context.document_version_id) for context in contexts})
        input_tokens = sum(int(chunk.token_count or 0) for chunk, _existing in pending)
        metadata: dict[str, object] = {
            "index_name": request.index_name,
            "index_version": request.index_version,
            "embedding_index_id": str(embedding_index.id),
            "chunk_count": len(pending),
            "source_document_count": len(source_document_ids),
            "document_version_count": len(document_version_ids),
            "source_document_ids": source_document_ids,
            "document_version_ids": document_version_ids,
            "estimated_input_tokens": input_tokens,
            "force_rebuild": request.force,
        }
        if len(company_ids) == 1:
            context = contexts[0]
            metadata.update(
                {
                    "company_id": str(context.company_id) if context.company_id else None,
                    "company_name": context.company_name,
                    "cik": context.cik,
                    "tickers": tickers,
                    "ticker": tickers[0] if len(tickers) == 1 else None,
                }
            )
        else:
            metadata.update(
                {
                    "company_count": len(company_ids),
                    "company_names": company_names,
                    "tickers": tickers,
                }
            )
        return metadata

    def _chunk_context(self, chunk: DocumentChunk) -> _ChunkEmbeddingContext:
        document_version = chunk.document_version or self._session.get(
            DocumentVersion, chunk.document_version_id
        )
        document: SourceDocument | None = None
        company: Company | None = None
        if document_version is not None:
            document = document_version.document
        if document is not None and document.company_id is not None:
            company = document.company
        tickers = (
            tuple(sorted({ticker.symbol.upper() for ticker in company.tickers if ticker.symbol}))
            if company is not None
            else ()
        )
        return _ChunkEmbeddingContext(
            company_id=company.id if company is not None else None,
            company_name=company.display_name if company is not None else None,
            cik=company.cik if company is not None else None,
            tickers=tickers,
            source_document_id=document.id if document is not None else None,
            document_version_id=chunk.document_version_id,
        )


def _embedding_tags(provider: str) -> tuple[str, ...]:
    return ("embedding", "indexing", provider)
