from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CitationMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)


def citation_metrics(
    predicted: set[tuple[str, str]], expected: set[tuple[str, str]]
) -> CitationMetrics:
    """Compute claim/evidence citation precision and recall."""

    true_positives = len(predicted & expected)
    false_positives = len(predicted - expected)
    false_negatives = len(expected - predicted)
    precision_denominator = true_positives + false_positives
    recall_denominator = true_positives + false_negatives
    return CitationMetrics(
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=true_positives / precision_denominator if precision_denominator else 1.0,
        recall=true_positives / recall_denominator if recall_denominator else 1.0,
    )
