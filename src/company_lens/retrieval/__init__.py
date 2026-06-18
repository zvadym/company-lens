"""Baseline and adaptive hierarchical retrieval services."""

from company_lens.retrieval.adaptive import AdaptiveRetrievalService, ContextAssembler
from company_lens.retrieval.adaptive_schemas import (
    AdaptiveRetrievalRequest,
    AdaptiveRetrievalResponse,
    RetrievalPlan,
    RetrievalTrace,
)
from company_lens.retrieval.embeddings import (
    DEFAULT_LOCAL_EMBEDDING_DIMENSIONS,
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    DEFAULT_OPENAI_EMBEDDING_DIMENSIONS,
    DEFAULT_OPENAI_EMBEDDING_MODEL,
    DEFAULT_OPENAI_INDEX_VERSION,
    LocalFeatureHashingEmbedder,
    OpenAIEmbedder,
    build_embedder,
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
    "AdaptiveRetrievalRequest",
    "AdaptiveRetrievalResponse",
    "AdaptiveRetrievalService",
    "ContextAssembler",
    "DEFAULT_LOCAL_EMBEDDING_DIMENSIONS",
    "DEFAULT_LOCAL_EMBEDDING_MODEL",
    "DEFAULT_OPENAI_EMBEDDING_DIMENSIONS",
    "DEFAULT_OPENAI_EMBEDDING_MODEL",
    "DEFAULT_OPENAI_INDEX_VERSION",
    "EmbeddingIndexingRequest",
    "EmbeddingIndexingResult",
    "EmbeddingIndexingService",
    "LocalFeatureHashingEmbedder",
    "OpenAIEmbedder",
    "RetrievalFilters",
    "RetrievalMode",
    "RetrievalPlan",
    "RetrievalRequest",
    "RetrievalResponse",
    "RetrievalResult",
    "RetrievalService",
    "RetrievalTrace",
    "build_embedder",
]
