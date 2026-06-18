from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from company_lens.db.models import ChunkEmbedding, DocumentChunk, EmbeddingIndex
from company_lens.retrieval.embeddings import Embedder, LocalFeatureHashingEmbedder
from company_lens.retrieval.schemas import EmbeddingIndexingRequest, EmbeddingIndexingResult


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
        failed = 0

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

            try:
                vectors = self._embedder.embed_texts([chunk.text for chunk, _ in pending])
                batch_indexed = 0
                batch_stale_rebuilt = 0
                for (chunk, existing), vector in zip(pending, vectors, strict=True):
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
            except Exception:
                self._session.rollback()
                failed += len(pending)

        return EmbeddingIndexingResult(
            index_id=embedding_index.id,
            index_name=embedding_index.name,
            index_version=embedding_index.index_version,
            embedding_model=embedding_index.embedding_model,
            dimensions=embedding_index.dimensions,
            indexed=indexed,
            skipped=skipped,
            stale_rebuilt=stale_rebuilt,
            failed=failed,
        )

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
        if request.limit is not None:
            statement = statement.limit(request.limit)
        return list(self._session.scalars(statement).all())
