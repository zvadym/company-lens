from __future__ import annotations

from fastapi.testclient import TestClient

from company_lens_reranker.app import create_app
from company_lens_reranker.schemas import RerankItem, RerankScore
from company_lens_reranker.scoring import ScoringError


class FakeScorer:
    model_name = "fake-cross-encoder"

    def __init__(self, *, ready_error: bool = False, scoring_error: bool = False) -> None:
        self.ready_error = ready_error
        self.scoring_error = scoring_error
        self.ready_calls = 0
        self.score_calls: list[tuple[str, tuple[RerankItem, ...]]] = []

    def ensure_ready(self) -> None:
        self.ready_calls += 1
        if self.ready_error:
            raise RuntimeError("private model load detail")

    def score(self, *, query: str, items: tuple[RerankItem, ...]) -> tuple[RerankScore, ...]:
        self.score_calls.append((query, items))
        if self.scoring_error:
            raise ScoringError("private scoring detail")
        return tuple(
            RerankScore(id=item.id, score=float(index)) for index, item in enumerate(items, start=1)
        )


def test_health_returns_ok_without_loading_model() -> None:
    scorer = FakeScorer()
    client = TestClient(create_app(scorer=scorer))  # type: ignore[arg-type]

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert scorer.ready_calls == 0


def test_ready_loads_model_and_returns_identity() -> None:
    scorer = FakeScorer()
    client = TestClient(create_app(scorer=scorer))  # type: ignore[arg-type]

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "model": "fake-cross-encoder"}
    assert scorer.ready_calls == 1


def test_ready_returns_sanitized_503_when_model_fails() -> None:
    client = TestClient(create_app(scorer=FakeScorer(ready_error=True)))  # type: ignore[arg-type]

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "model_not_ready", "message": "Reranker model is not ready."}
    }


def test_rerank_returns_scores_for_request_items() -> None:
    scorer = FakeScorer()
    client = TestClient(create_app(scorer=scorer))  # type: ignore[arg-type]

    response = client.post(
        "/rerank",
        json={
            "query": "risk",
            "items": [{"id": "a", "text": "first"}, {"id": "b", "text": "second"}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "model": "fake-cross-encoder",
        "scores": [{"id": "a", "score": 1.0}, {"id": "b", "score": 2.0}],
    }
    assert scorer.score_calls[0][0] == "risk"


def test_rerank_rejects_invalid_payload_with_sanitized_400() -> None:
    client = TestClient(create_app(scorer=FakeScorer()))  # type: ignore[arg-type]

    response = client.post("/rerank", json={"query": "risk", "items": [{"id": "", "text": ""}]})

    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "Rerank request is invalid."}
    }


def test_rerank_returns_sanitized_500_when_scoring_fails() -> None:
    client = TestClient(create_app(scorer=FakeScorer(scoring_error=True)))  # type: ignore[arg-type]

    response = client.post(
        "/rerank",
        json={"query": "risk", "items": [{"id": "a", "text": "first"}]},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "scoring_failed", "message": "Reranker scoring failed."}
    }
