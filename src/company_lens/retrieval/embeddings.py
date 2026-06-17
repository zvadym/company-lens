from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

DEFAULT_LOCAL_EMBEDDING_MODEL = "local-feature-hashing-v1"
DEFAULT_LOCAL_EMBEDDING_DIMENSIONS = 384

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class LocalFeatureHashingEmbedder:
    """Deterministic embedding backend for local retrieval and repeatable tests."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_LOCAL_EMBEDDING_MODEL,
        dimensions: int = DEFAULT_LOCAL_EMBEDDING_DIMENSIONS,
    ) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive.")
        self.model_name = model_name
        self.dimensions = dimensions

    def embed_query(self, text: str) -> list[float]:
        return self.embed_text(text)

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot_product = sum(
        left_value * right_value for left_value, right_value in zip(left, right, strict=False)
    )
    return dot_product / (left_norm * right_norm)


def vector_to_pg(value: Sequence[float]) -> str:
    return "[" + ",".join(f"{item:.12g}" for item in value) + "]"


def _tokens(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())
