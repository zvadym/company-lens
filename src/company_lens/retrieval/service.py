from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import Select, select, text
from sqlalchemy.orm import Session

from company_lens.db.models import (
    ChunkEmbedding,
    Company,
    DocumentChunk,
    DocumentSummary,
    DocumentVersion,
    EmbeddingIndex,
    FilingSection,
    SectionSummary,
    SourceDocument,
)
from company_lens.processing.text import jaccard, normalize_for_fingerprint, shingle_fingerprint
from company_lens.retrieval.embeddings import (
    LocalFeatureHashingEmbedder,
    cosine_similarity,
    vector_to_pg,
)
from company_lens.retrieval.rerank import NoopReranker, Reranker, RerankInput
from company_lens.retrieval.schemas import (
    RetrievalDiagnostics,
    RetrievalFilters,
    RetrievalRequest,
    RetrievalResponse,
    RetrievalResult,
    RetrievalScores,
)


@dataclass
class _Candidate:
    chunk_id: uuid.UUID
    lexical_score: float | None = None
    vector_score: float | None = None
    hybrid_score: float | None = None
    dense_rank: int | None = None
    lexical_rank: int | None = None
    reranker_score: float | None = None
    reranker_rank: int | None = None
    diversity_limited: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def sort_score(self) -> float:
        if self.reranker_score is not None:
            return self.reranker_score
        if self.hybrid_score is not None:
            return self.hybrid_score
        if self.vector_score is not None:
            return self.vector_score
        return self.lexical_score or 0.0


@dataclass(frozen=True)
class _ChunkContext:
    chunk: DocumentChunk
    section: FilingSection
    version: DocumentVersion
    document: SourceDocument
    company: Company | None
    section_summary: str | None
    document_summary: str | None


class RetrievalService:
    def __init__(
        self,
        *,
        session: Session,
        embedder: LocalFeatureHashingEmbedder | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._session = session
        self._embedder = embedder or LocalFeatureHashingEmbedder()
        self._reranker = reranker or NoopReranker()

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        embedding_index = self._embedding_index(request)
        warnings: list[str] = []
        stale_embeddings = self._stale_embedding_count(embedding_index) if embedding_index else 0

        dense_candidates: list[_Candidate] = []
        lexical_candidates: list[_Candidate] = []
        if request.mode in {"dense", "hybrid"}:
            if embedding_index is None:
                warnings.append("missing_embedding_index")
            else:
                dense_candidates = self._dense_candidates(request, embedding_index)
            if not dense_candidates:
                warnings.append("missing_dense_candidates")

        if request.mode in {"lexical", "hybrid"}:
            lexical_candidates = self._lexical_candidates(request)

        candidates = self._merge_candidates(
            mode=request.mode,
            dense_candidates=dense_candidates,
            lexical_candidates=lexical_candidates,
        )
        candidates = self._rerank(request, candidates)
        contexts = self._contexts([candidate.chunk_id for candidate in candidates], request)
        candidates, deduped = self._dedupe(candidates, contexts, request)
        candidates, diversity_limited = self._apply_diversity(candidates, contexts, request)

        results = self._build_results(
            request=request,
            candidates=candidates[: request.top_k],
            contexts=contexts,
            embedding_index=embedding_index,
            warnings=tuple(warnings),
        )
        return RetrievalResponse(
            query=request.query,
            mode=request.mode,
            results=tuple(results),
            diagnostics={
                "dense_candidates": len(dense_candidates),
                "lexical_candidates": len(lexical_candidates),
                "candidate_count": len(candidates),
                "deduped_candidates": deduped,
                "diversity_limited_candidates": diversity_limited,
                "stale_embeddings": stale_embeddings,
                "warnings": tuple(warnings),
                "reranker": self._reranker.name,
            },
        )

    def _embedding_index(self, request: RetrievalRequest) -> EmbeddingIndex | None:
        return self._session.scalar(
            select(EmbeddingIndex).where(
                EmbeddingIndex.name == request.index_name,
                EmbeddingIndex.index_version == request.index_version,
            )
        )

    def _dense_candidates(
        self,
        request: RetrievalRequest,
        embedding_index: EmbeddingIndex,
    ) -> list[_Candidate]:
        if self._dialect_name() == "postgresql":
            return self._postgres_dense_candidates(request, embedding_index)
        return self._python_dense_candidates(request, embedding_index)

    def _postgres_dense_candidates(
        self,
        request: RetrievalRequest,
        embedding_index: EmbeddingIndex,
    ) -> list[_Candidate]:
        where_sql, params = self._filter_sql(request.filters)
        query_vector = vector_to_pg(self._embedder.embed_query(request.query))
        params.update(
            {
                "embedding_index_id": embedding_index.id,
                "query_embedding": query_vector,
                "limit": request.dense_candidate_limit,
            }
        )
        sql = f"""
            SELECT c.id AS chunk_id,
                   1 - (e.embedding <=> CAST(:query_embedding AS vector)) AS vector_score
            FROM chunk_embeddings e
            JOIN document_chunks c ON c.id = e.chunk_id
            JOIN filing_sections fs ON fs.id = c.section_id
            JOIN document_versions dv ON dv.id = c.document_version_id
            JOIN source_documents sd ON sd.id = dv.document_id
            LEFT JOIN companies co ON co.id = sd.company_id
            WHERE e.embedding_index_id = :embedding_index_id
              AND e.content_hash = c.content_hash
              {where_sql}
            ORDER BY e.embedding <=> CAST(:query_embedding AS vector), c.id
            LIMIT :limit
        """
        rows = self._session.execute(text(sql), params).mappings().all()
        return [
            _Candidate(
                chunk_id=row["chunk_id"],
                vector_score=float(row["vector_score"] or 0.0),
                dense_rank=index + 1,
            )
            for index, row in enumerate(rows)
        ]

    def _python_dense_candidates(
        self,
        request: RetrievalRequest,
        embedding_index: EmbeddingIndex,
    ) -> list[_Candidate]:
        query_embedding = self._embedder.embed_query(request.query)
        statement = self._base_chunk_embedding_select(request.filters).where(
            ChunkEmbedding.embedding_index_id == embedding_index.id,
            ChunkEmbedding.content_hash == DocumentChunk.content_hash,
        )
        rows = self._session.execute(statement).all()
        candidates = [
            _Candidate(
                chunk_id=chunk.id,
                vector_score=cosine_similarity(query_embedding, embedding.embedding),
            )
            for chunk, embedding in rows
        ]
        candidates.sort(key=lambda item: (-1 * (item.vector_score or 0.0), str(item.chunk_id)))
        limited = candidates[: request.dense_candidate_limit]
        for index, candidate in enumerate(limited):
            candidate.dense_rank = index + 1
        return limited

    def _lexical_candidates(self, request: RetrievalRequest) -> list[_Candidate]:
        if self._dialect_name() == "postgresql":
            return self._postgres_lexical_candidates(request)
        return self._python_lexical_candidates(request)

    def _postgres_lexical_candidates(self, request: RetrievalRequest) -> list[_Candidate]:
        where_sql, params = self._filter_sql(request.filters)
        params.update({"query": request.query, "limit": request.lexical_candidate_limit})
        sql = f"""
            WITH query AS (SELECT websearch_to_tsquery('english', :query) AS value)
            SELECT c.id AS chunk_id,
                   ts_rank_cd(c.search_vector, query.value) AS lexical_score
            FROM query, document_chunks c
            JOIN filing_sections fs ON fs.id = c.section_id
            JOIN document_versions dv ON dv.id = c.document_version_id
            JOIN source_documents sd ON sd.id = dv.document_id
            LEFT JOIN companies co ON co.id = sd.company_id
            WHERE c.search_vector @@ query.value
              {where_sql}
            ORDER BY lexical_score DESC, c.id
            LIMIT :limit
        """
        rows = self._session.execute(text(sql), params).mappings().all()
        return [
            _Candidate(
                chunk_id=row["chunk_id"],
                lexical_score=float(row["lexical_score"] or 0.0),
                lexical_rank=index + 1,
            )
            for index, row in enumerate(rows)
        ]

    def _python_lexical_candidates(self, request: RetrievalRequest) -> list[_Candidate]:
        query_terms = set(normalize_for_fingerprint(request.query).split())
        if not query_terms:
            return []
        rows = self._session.execute(self._base_chunk_select(request.filters)).scalars().all()
        candidates: list[_Candidate] = []
        for chunk in rows:
            chunk_terms = normalize_for_fingerprint(chunk.text).split()
            if not chunk_terms:
                continue
            term_counts: defaultdict[str, int] = defaultdict(int)
            for term in chunk_terms:
                term_counts[term] += 1
            score = sum(term_counts[term] for term in query_terms) / len(chunk_terms)
            if score > 0:
                candidates.append(_Candidate(chunk_id=chunk.id, lexical_score=score))
        candidates.sort(key=lambda item: (-1 * (item.lexical_score or 0.0), str(item.chunk_id)))
        limited = candidates[: request.lexical_candidate_limit]
        for index, candidate in enumerate(limited):
            candidate.lexical_rank = index + 1
        return limited

    def _merge_candidates(
        self,
        *,
        mode: str,
        dense_candidates: list[_Candidate],
        lexical_candidates: list[_Candidate],
    ) -> list[_Candidate]:
        if mode == "dense":
            return dense_candidates
        if mode == "lexical":
            return lexical_candidates

        merged: dict[uuid.UUID, _Candidate] = {}
        for candidate in dense_candidates:
            merged[candidate.chunk_id] = _Candidate(
                chunk_id=candidate.chunk_id,
                vector_score=candidate.vector_score,
                dense_rank=candidate.dense_rank,
            )
        for candidate in lexical_candidates:
            current = merged.get(candidate.chunk_id)
            if current is None:
                current = _Candidate(chunk_id=candidate.chunk_id)
                merged[candidate.chunk_id] = current
            current.lexical_score = candidate.lexical_score
            current.lexical_rank = candidate.lexical_rank

        for candidate in merged.values():
            candidate.hybrid_score = _rrf(candidate.dense_rank) + _rrf(candidate.lexical_rank)
        return sorted(
            merged.values(),
            key=lambda item: (-1 * (item.hybrid_score or 0.0), str(item.chunk_id)),
        )

    def _rerank(self, request: RetrievalRequest, candidates: list[_Candidate]) -> list[_Candidate]:
        contexts = self._contexts([candidate.chunk_id for candidate in candidates], request)
        inputs = tuple(
            RerankInput(
                chunk_id=str(candidate.chunk_id),
                query=request.query,
                text=contexts[candidate.chunk_id].chunk.text,
                score=candidate.sort_score,
            )
            for candidate in candidates
            if candidate.chunk_id in contexts
        )
        outputs = {uuid.UUID(output.chunk_id): output for output in self._reranker.rerank(inputs)}
        for candidate in candidates:
            output = outputs.get(candidate.chunk_id)
            if output is not None:
                candidate.reranker_score = output.score
        candidates.sort(key=lambda item: (-1 * item.sort_score, str(item.chunk_id)))
        for index, candidate in enumerate(candidates):
            candidate.reranker_rank = index + 1
        return candidates

    def _contexts(
        self,
        chunk_ids: list[uuid.UUID],
        request: RetrievalRequest,
    ) -> dict[uuid.UUID, _ChunkContext]:
        if not chunk_ids:
            return {}
        statement = (
            select(DocumentChunk, FilingSection, DocumentVersion, SourceDocument, Company)
            .join(FilingSection, FilingSection.id == DocumentChunk.section_id)
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
            .join(SourceDocument, SourceDocument.id == DocumentVersion.document_id)
            .outerjoin(Company, Company.id == SourceDocument.company_id)
            .where(DocumentChunk.id.in_(chunk_ids))
        )
        section_summaries: dict[uuid.UUID, str] = {}
        document_summaries: dict[uuid.UUID, str] = {}
        if request.include_parent_text:
            for section_summary in self._session.scalars(select(SectionSummary)).all():
                section_summaries.setdefault(
                    section_summary.section_id,
                    section_summary.summary_text,
                )
            for document_summary in self._session.scalars(select(DocumentSummary)).all():
                document_summaries.setdefault(
                    document_summary.document_version_id,
                    document_summary.summary_text,
                )

        contexts: dict[uuid.UUID, _ChunkContext] = {}
        for chunk, section, version, document, company in self._session.execute(statement).all():
            contexts[chunk.id] = _ChunkContext(
                chunk=chunk,
                section=section,
                version=version,
                document=document,
                company=company,
                section_summary=section_summaries.get(section.id),
                document_summary=document_summaries.get(version.id),
            )
        return contexts

    def _dedupe(
        self,
        candidates: list[_Candidate],
        contexts: dict[uuid.UUID, _ChunkContext],
        request: RetrievalRequest,
    ) -> tuple[list[_Candidate], int]:
        kept: list[_Candidate] = []
        seen_hashes: set[str] = set()
        seen_fingerprints: list[frozenset[str]] = []
        removed = 0
        for candidate in candidates:
            context = contexts.get(candidate.chunk_id)
            if context is None:
                removed += 1
                continue
            if context.chunk.content_hash in seen_hashes:
                removed += 1
                continue
            fingerprint = shingle_fingerprint(context.chunk.text)
            if any(
                jaccard(fingerprint, existing) >= request.near_duplicate_threshold
                for existing in seen_fingerprints
            ):
                removed += 1
                continue
            seen_hashes.add(context.chunk.content_hash)
            seen_fingerprints.append(fingerprint)
            kept.append(candidate)
        return kept, removed

    def _apply_diversity(
        self,
        candidates: list[_Candidate],
        contexts: dict[uuid.UUID, _ChunkContext],
        request: RetrievalRequest,
    ) -> tuple[list[_Candidate], int]:
        accepted: list[_Candidate] = []
        deferred: list[_Candidate] = []
        document_counts: dict[uuid.UUID, int] = defaultdict(int)
        period_counts: dict[str, int] = defaultdict(int)
        limited = 0
        for candidate in candidates:
            context = contexts.get(candidate.chunk_id)
            if context is None:
                continue
            period_key = _period_key(context.document)
            document_limited = document_counts[context.document.id] >= request.max_per_document
            period_limited = (
                period_key is not None and period_counts[period_key] >= request.max_per_period
            )
            if document_limited or period_limited:
                candidate.diversity_limited = True
                deferred.append(candidate)
                limited += 1
                continue
            accepted.append(candidate)
            document_counts[context.document.id] += 1
            if period_key is not None:
                period_counts[period_key] += 1
        return [*accepted, *deferred], limited

    def _build_results(
        self,
        *,
        request: RetrievalRequest,
        candidates: list[_Candidate],
        contexts: dict[uuid.UUID, _ChunkContext],
        embedding_index: EmbeddingIndex | None,
        warnings: tuple[str, ...],
    ) -> list[RetrievalResult]:
        results: list[RetrievalResult] = []
        for rank, candidate in enumerate(candidates, start=1):
            context = contexts.get(candidate.chunk_id)
            if context is None:
                continue
            document = context.document
            company = context.company
            results.append(
                RetrievalResult(
                    chunk_id=context.chunk.id,
                    source_document_id=document.id,
                    document_version_id=context.version.id,
                    section_id=context.section.id,
                    company_id=company.id if company is not None else None,
                    company_display_name=company.display_name if company is not None else None,
                    document_title=document.title,
                    document_kind=document.kind.value,
                    source_system=document.source_system,
                    stable_source_id=document.stable_source_id,
                    source_url=document.source_url,
                    accession_number=document.accession_number,
                    filing_form=document.filing_form,
                    filing_date=document.filing_date,
                    period_end=document.period_end,
                    fiscal_year=document.fiscal_year,
                    fiscal_period=document.fiscal_period,
                    section_code=context.section.section_code,
                    section_title=context.section.title,
                    page_start=context.chunk.page_start,
                    page_end=context.chunk.page_end,
                    char_start=context.chunk.char_start,
                    char_end=context.chunk.char_end,
                    chunk_index=context.chunk.chunk_index,
                    text=context.chunk.text,
                    content_hash=context.chunk.content_hash,
                    section_summary=context.section_summary,
                    document_summary=context.document_summary,
                    scores=RetrievalScores(
                        lexical_score=candidate.lexical_score,
                        vector_score=candidate.vector_score,
                        reranker_score=candidate.reranker_score,
                        hybrid_score=candidate.hybrid_score,
                    ),
                    diagnostics=RetrievalDiagnostics(
                        selected_strategy=request.mode,
                        rank=rank,
                        dense_rank=candidate.dense_rank,
                        lexical_rank=candidate.lexical_rank,
                        reranker_rank=candidate.reranker_rank,
                        embedding_index_name=embedding_index.name if embedding_index else None,
                        embedding_index_version=(
                            embedding_index.index_version if embedding_index else None
                        ),
                        embedding_model=(
                            embedding_index.embedding_model if embedding_index else None
                        ),
                        diversity_limited=candidate.diversity_limited,
                        matched_filters=_matched_filter_payload(request.filters),
                        warnings=warnings,
                    ),
                )
            )
        return results

    def _base_chunk_select(self, filters: RetrievalFilters) -> Select[tuple[DocumentChunk]]:
        statement = (
            select(DocumentChunk)
            .join(FilingSection, FilingSection.id == DocumentChunk.section_id)
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
            .join(SourceDocument, SourceDocument.id == DocumentVersion.document_id)
            .outerjoin(Company, Company.id == SourceDocument.company_id)
        )
        return cast(Select[tuple[DocumentChunk]], _apply_filter_conditions(statement, filters))

    def _base_chunk_embedding_select(
        self,
        filters: RetrievalFilters,
    ) -> Select[tuple[DocumentChunk, ChunkEmbedding]]:
        statement = (
            select(DocumentChunk, ChunkEmbedding)
            .join(FilingSection, FilingSection.id == DocumentChunk.section_id)
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
            .join(SourceDocument, SourceDocument.id == DocumentVersion.document_id)
            .outerjoin(Company, Company.id == SourceDocument.company_id)
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
        )
        return cast(
            Select[tuple[DocumentChunk, ChunkEmbedding]],
            _apply_filter_conditions(statement, filters),
        )

    def _filter_sql(self, filters: RetrievalFilters) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        self._add_in_sql(clauses, params, "sd.company_id", "company_id", filters.company_ids)
        self._add_in_sql(
            clauses,
            params,
            "dv.id",
            "document_version_id",
            filters.document_version_ids,
        )
        self._add_in_sql(
            clauses,
            params,
            "sd.kind",
            "document_kind",
            tuple(item.name for item in filters.document_kinds),
        )
        self._add_in_sql(clauses, params, "sd.filing_form", "filing_form", filters.filing_forms)
        if filters.filing_date_from:
            clauses.append("AND sd.filing_date >= :filing_date_from")
            params["filing_date_from"] = filters.filing_date_from
        if filters.filing_date_to:
            clauses.append("AND sd.filing_date <= :filing_date_to")
            params["filing_date_to"] = filters.filing_date_to
        if filters.period_end_from:
            clauses.append("AND sd.period_end >= :period_end_from")
            params["period_end_from"] = filters.period_end_from
        if filters.period_end_to:
            clauses.append("AND sd.period_end <= :period_end_to")
            params["period_end_to"] = filters.period_end_to
        self._add_in_sql(clauses, params, "sd.fiscal_year", "fiscal_year", filters.fiscal_years)
        self._add_in_sql(
            clauses,
            params,
            "sd.fiscal_period",
            "fiscal_period",
            filters.fiscal_periods,
        )
        self._add_in_sql(clauses, params, "fs.section_code", "section_code", filters.section_codes)
        self._add_in_sql(
            clauses,
            params,
            "sd.source_system",
            "source_system",
            filters.source_systems,
        )
        return "\n".join(clauses), params

    def _add_in_sql(
        self,
        clauses: list[str],
        params: dict[str, Any],
        column: str,
        prefix: str,
        values: tuple[Any, ...],
    ) -> None:
        if not values:
            return
        keys: list[str] = []
        for index, value in enumerate(values):
            key = f"{prefix}_{index}"
            keys.append(f":{key}")
            params[key] = value
        clauses.append(f"AND {column} IN ({', '.join(keys)})")

    def _stale_embedding_count(self, embedding_index: EmbeddingIndex | None) -> int:
        if embedding_index is None:
            return 0
        statement = (
            select(ChunkEmbedding)
            .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
            .where(
                ChunkEmbedding.embedding_index_id == embedding_index.id,
                ChunkEmbedding.content_hash != DocumentChunk.content_hash,
            )
        )
        return len(self._session.scalars(statement).all())

    def _dialect_name(self) -> str:
        bind = self._session.get_bind()
        return bind.dialect.name


def _apply_filter_conditions(
    statement: Select[Any],
    filters: RetrievalFilters,
) -> Select[Any]:
    if filters.company_ids:
        statement = statement.where(SourceDocument.company_id.in_(filters.company_ids))
    if filters.document_version_ids:
        statement = statement.where(DocumentVersion.id.in_(filters.document_version_ids))
    if filters.document_kinds:
        statement = statement.where(SourceDocument.kind.in_(filters.document_kinds))
    if filters.filing_forms:
        statement = statement.where(SourceDocument.filing_form.in_(filters.filing_forms))
    if filters.filing_date_from:
        statement = statement.where(SourceDocument.filing_date >= filters.filing_date_from)
    if filters.filing_date_to:
        statement = statement.where(SourceDocument.filing_date <= filters.filing_date_to)
    if filters.period_end_from:
        statement = statement.where(SourceDocument.period_end >= filters.period_end_from)
    if filters.period_end_to:
        statement = statement.where(SourceDocument.period_end <= filters.period_end_to)
    if filters.fiscal_years:
        statement = statement.where(SourceDocument.fiscal_year.in_(filters.fiscal_years))
    if filters.fiscal_periods:
        statement = statement.where(SourceDocument.fiscal_period.in_(filters.fiscal_periods))
    if filters.section_codes:
        statement = statement.where(FilingSection.section_code.in_(filters.section_codes))
    if filters.source_systems:
        statement = statement.where(SourceDocument.source_system.in_(filters.source_systems))
    return statement


def _matched_filter_payload(filters: RetrievalFilters) -> dict[str, object]:
    payload = filters.model_dump(mode="json")
    return {key: value for key, value in payload.items() if value not in (None, [], ())}


def _period_key(document: SourceDocument) -> str | None:
    if document.fiscal_year is not None and document.fiscal_period:
        return f"{document.fiscal_year}:{document.fiscal_period}"
    if document.period_end is not None:
        return document.period_end.isoformat()
    return None


def _rrf(rank: int | None, *, k: int = 60) -> float:
    if rank is None:
        return 0.0
    return 1.0 / (k + rank)
