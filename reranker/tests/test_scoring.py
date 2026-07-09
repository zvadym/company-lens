from __future__ import annotations

from collections.abc import Sequence

import pytest

from company_lens_reranker.schemas import RerankItem
from company_lens_reranker.scoring import CrossEncoderScorer, ScoringError


class FakeCrossEncoder:
    def __init__(self, scores: Sequence[float]) -> None:
        self.scores = scores
        self.calls: list[dict[str, object]] = []

    def predict(
        self,
        sentences: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
    ) -> Sequence[float]:
        self.calls.append(
            {
                "sentences": tuple(sentences),
                "batch_size": batch_size,
                "show_progress_bar": show_progress_bar,
            }
        )
        return self.scores


def test_cross_encoder_scorer_loads_model_lazily_and_scores_batch() -> None:
    fake_model = FakeCrossEncoder([0.1, 0.9])
    loaded: list[tuple[str, int]] = []
    scorer = CrossEncoderScorer(
        model_name="test-model",
        batch_size=8,
        max_length=256,
        model_factory=lambda model_name, max_length: (
            loaded.append((model_name, max_length)) or fake_model
        ),
    )

    assert scorer.is_ready is False

    scores = scorer.score(
        query="revenue risk",
        items=(
            RerankItem(id="a", text="weak passage"),
            RerankItem(id="b", text="strong passage"),
        ),
    )

    assert scorer.is_ready is True
    assert loaded == [("test-model", 256)]
    assert fake_model.calls == [
        {
            "sentences": (
                ("revenue risk", "weak passage"),
                ("revenue risk", "strong passage"),
            ),
            "batch_size": 8,
            "show_progress_bar": False,
        }
    ]
    assert [(score.id, score.score) for score in scores] == [("a", 0.1), ("b", 0.9)]


def test_cross_encoder_scorer_reuses_loaded_model() -> None:
    fake_model = FakeCrossEncoder([1.0])
    load_count = 0

    def factory(_model_name: str, _max_length: int) -> FakeCrossEncoder:
        nonlocal load_count
        load_count += 1
        return fake_model

    scorer = CrossEncoderScorer(
        model_name="test-model",
        batch_size=4,
        max_length=128,
        model_factory=factory,
    )

    scorer.ensure_ready()
    scorer.score(query="risk", items=(RerankItem(id="a", text="passage"),))

    assert load_count == 1


def test_cross_encoder_scorer_rejects_invalid_score_count() -> None:
    scorer = CrossEncoderScorer(
        model_name="test-model",
        batch_size=4,
        max_length=128,
        model_factory=lambda _model_name, _max_length: FakeCrossEncoder([1.0]),
    )

    with pytest.raises(ScoringError, match="score count"):
        scorer.score(
            query="risk",
            items=(
                RerankItem(id="a", text="first"),
                RerankItem(id="b", text="second"),
            ),
        )


def test_cross_encoder_scorer_rejects_non_finite_scores() -> None:
    scorer = CrossEncoderScorer(
        model_name="test-model",
        batch_size=4,
        max_length=128,
        model_factory=lambda _model_name, _max_length: FakeCrossEncoder([float("inf")]),
    )

    with pytest.raises(ScoringError, match="non-finite"):
        scorer.score(query="risk", items=(RerankItem(id="a", text="passage"),))
