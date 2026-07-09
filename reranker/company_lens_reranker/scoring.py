from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from company_lens_reranker.schemas import RerankItem, RerankScore


class RerankerServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COMPANY_LENS_RERANKER_SERVICE_",
        extra="ignore",
    )

    model_name: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    batch_size: int = Field(default=16, ge=1, le=256)
    max_length: int = Field(default=512, ge=32, le=8192)


class CrossEncoderLike(Protocol):
    def predict(
        self,
        sentences: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
    ) -> Sequence[float]:
        """Score query-document pairs."""


class ScoringError(RuntimeError):
    """Sanitized scoring failure returned through service error boundaries."""


ModelFactory = Callable[[str, int], CrossEncoderLike]


class CrossEncoderScorer:
    def __init__(
        self,
        *,
        model_name: str,
        batch_size: int,
        max_length: int,
        model_factory: ModelFactory | None = None,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self._model_factory = model_factory
        self._model: CrossEncoderLike | None = None

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def ensure_ready(self) -> None:
        self._load_model()

    def score(self, *, query: str, items: tuple[RerankItem, ...]) -> tuple[RerankScore, ...]:
        if not items:
            return ()
        model = self._load_model()
        pairs = tuple((query, item.text) for item in items)
        try:
            raw_scores = model.predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise ScoringError("Reranker scoring failed.") from exc
        if len(raw_scores) != len(items):
            raise ScoringError("Reranker returned an invalid score count.")
        scores: list[RerankScore] = []
        for item, raw_score in zip(items, raw_scores, strict=True):
            score = _as_finite_float(raw_score)
            scores.append(RerankScore(id=item.id, score=score))
        return tuple(scores)

    def _load_model(self) -> CrossEncoderLike:
        if self._model is None:
            factory = self._model_factory or _default_model_factory
            self._model = factory(self.model_name, self.max_length)
        return self._model


def build_scorer(settings: RerankerServiceSettings | None = None) -> CrossEncoderScorer:
    resolved = settings or RerankerServiceSettings()
    return CrossEncoderScorer(
        model_name=resolved.model_name,
        batch_size=resolved.batch_size,
        max_length=resolved.max_length,
    )


def _default_model_factory(model_name: str, max_length: int) -> CrossEncoderLike:
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name, max_length=max_length)


def _as_finite_float(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoringError("Reranker returned a non-numeric score.") from exc
    if not math.isfinite(score):
        raise ScoringError("Reranker returned a non-finite score.")
    return score
