from __future__ import annotations

import pytest
from pydantic import ValidationError

from company_lens_reranker.schemas import RerankRequest, RerankResponse, RerankScore


def test_rerank_request_strips_query_and_items() -> None:
    request = RerankRequest(
        query="  revenue risk  ",
        items=({"id": " chunk-1 ", "text": " relevant filing passage "},),
    )

    assert request.query == "revenue risk"
    assert request.items[0].id == "chunk-1"
    assert request.items[0].text == "relevant filing passage"


def test_rerank_request_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError, match="unique"):
        RerankRequest(
            query="risk",
            items=(
                {"id": "chunk-1", "text": "first"},
                {"id": "chunk-1", "text": "second"},
            ),
        )


def test_rerank_request_rejects_blank_text() -> None:
    with pytest.raises(ValidationError):
        RerankRequest(query="risk", items=({"id": "chunk-1", "text": "   "},))


def test_rerank_request_caps_candidate_count() -> None:
    with pytest.raises(ValidationError):
        RerankRequest(
            query="risk",
            items=tuple({"id": f"chunk-{index}", "text": "text"} for index in range(501)),
        )


def test_rerank_response_rejects_non_finite_scores() -> None:
    with pytest.raises(ValidationError):
        RerankScore(id="chunk-1", score=float("nan"))


def test_rerank_response_requires_model_identity() -> None:
    with pytest.raises(ValidationError):
        RerankResponse(model=" ", scores=())
