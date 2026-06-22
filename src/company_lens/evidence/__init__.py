"""Evidence registry, claim extraction, validation, and evaluation contracts."""

from company_lens.evidence.claims import extract_claims
from company_lens.evidence.evaluation import CitationMetrics, citation_metrics
from company_lens.evidence.registry import EvidenceRegistry
from company_lens.evidence.schemas import (
    AnswerValidation,
    CitationReference,
    ClaimRecord,
    ClaimValidation,
    EvidenceEnvelope,
    EvidenceKind,
    EvidenceMetadata,
    SemanticSupportResult,
    SemanticSupportStatus,
    SourcePreview,
    SourceStatus,
    ValidationIssue,
)
from company_lens.evidence.validation import AnswerValidator

__all__ = [
    "AnswerValidation",
    "AnswerValidator",
    "CitationMetrics",
    "CitationReference",
    "ClaimRecord",
    "ClaimValidation",
    "EvidenceEnvelope",
    "EvidenceKind",
    "EvidenceMetadata",
    "EvidenceRegistry",
    "SemanticSupportResult",
    "SemanticSupportStatus",
    "SourcePreview",
    "SourceStatus",
    "ValidationIssue",
    "citation_metrics",
    "extract_claims",
]
