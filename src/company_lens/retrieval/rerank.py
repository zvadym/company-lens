from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RerankInput:
    chunk_id: str
    query: str
    text: str
    score: float


@dataclass(frozen=True)
class RerankOutput:
    chunk_id: str
    score: float


class Reranker(Protocol):
    name: str

    def rerank(self, items: tuple[RerankInput, ...]) -> tuple[RerankOutput, ...]:
        """Return replacement scores for the input items."""


class NoopReranker:
    name = "noop-reranker-v1"

    def rerank(self, items: tuple[RerankInput, ...]) -> tuple[RerankOutput, ...]:
        return tuple(RerankOutput(chunk_id=item.chunk_id, score=item.score) for item in items)
