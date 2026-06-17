"""Baseline retrieval services for dense, lexical, and hybrid chunk search."""

from company_lens.retrieval.embeddings import (
    DEFAULT_LOCAL_EMBEDDING_DIMENSIONS,
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    LocalFeatureHashingEmbedder,
)
from company_lens.retrieval.indexing import EmbeddingIndexingService
from company_lens.retrieval.schemas import (
    EmbeddingIndexingRequest,
    EmbeddingIndexingResult,
    RetrievalFilters,
    RetrievalMode,
    RetrievalRequest,
    RetrievalResponse,
    RetrievalResult,
)
from company_lens.retrieval.service import RetrievalService

__all__ = [
    "DEFAULT_LOCAL_EMBEDDING_DIMENSIONS",
    "DEFAULT_LOCAL_EMBEDDING_MODEL",
    "EmbeddingIndexingRequest",
    "EmbeddingIndexingResult",
    "EmbeddingIndexingService",
    "LocalFeatureHashingEmbedder",
    "RetrievalFilters",
    "RetrievalMode",
    "RetrievalRequest",
    "RetrievalResponse",
    "RetrievalResult",
    "RetrievalService",
]
