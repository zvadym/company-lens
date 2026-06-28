from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Any, Literal, Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from company_lens.observability.telemetry import (
    current_embedding_observation,
    observe_operation,
    record_embedding,
)
from company_lens.processing.text import TOKEN_ENCODING
from company_lens.reliability import CircuitBreaker, RetryPolicy, call_with_resilience

DEFAULT_LOCAL_EMBEDDING_MODEL = "local-feature-hashing-v1"
DEFAULT_LOCAL_EMBEDDING_DIMENSIONS = 384
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_OPENAI_EMBEDDING_DIMENSIONS = 384
DEFAULT_OPENAI_INDEX_VERSION = "openai-text-embedding-3-small-384.v1"
OPENAI_EMBEDDING_MAX_INPUT_TOKENS = 8192

EmbeddingProvider = Literal["local", "openai"]

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    model_name: str
    dimensions: int
    provider: str

    def embed_query(self, text: str) -> list[float]: ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


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
        self.provider = "local_feature_hashing"

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


class OpenAIEmbedder:
    """OpenAI embeddings backend with configurable reduced dimensions."""

    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str = DEFAULT_OPENAI_EMBEDDING_MODEL,
        dimensions: int = DEFAULT_OPENAI_EMBEDDING_DIMENSIONS,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        circuit_breaker_failure_threshold: int = 5,
        circuit_breaker_recovery_seconds: float = 30.0,
        client: Any | None = None,
    ) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive.")
        self.model_name = model_name
        self.dimensions = dimensions
        self._retry_policy = RetryPolicy(max_attempts=max(1, max_retries + 1))
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=circuit_breaker_failure_threshold,
            recovery_seconds=circuit_breaker_recovery_seconds,
        )
        self._client = client or OpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts((text,))[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = [text.strip() for text in texts]
        if not inputs:
            return []
        if any(not text for text in inputs):
            raise ValueError("OpenAI embedding inputs must not be empty.")
        input_tokens = 0
        for index, text in enumerate(inputs):
            token_count = len(TOKEN_ENCODING.encode(text))
            input_tokens += token_count
            if token_count > OPENAI_EMBEDDING_MAX_INPUT_TOKENS:
                raise EmbeddingInputTooLongError(
                    input_index=index,
                    token_count=token_count,
                    max_tokens=OPENAI_EMBEDDING_MAX_INPUT_TOKENS,
                )

        with observe_operation(
            "model.embed",
            kind="embedding",
            attributes={
                "gen_ai.system": "openai",
                "gen_ai.request.model": self.model_name,
                "company_lens.embedding.input_count": len(inputs),
                "gen_ai.usage.input_tokens": input_tokens,
            },
        ):
            response = call_with_resilience(
                lambda: self._client.embeddings.create(
                    model=self.model_name,
                    input=inputs,
                    dimensions=self.dimensions,
                    encoding_format="float",
                ),
                provider="openai_embeddings",
                retry_policy=self._retry_policy,
                circuit_breaker=self._circuit_breaker,
                retry_if=_retryable_openai_error,
            )
            observation = current_embedding_observation()
            record_embedding(
                model=_response_model(response, self.model_name),
                input_tokens=_embedding_input_tokens(response, fallback=input_tokens),
                input_count=len(inputs),
                dimensions=self.dimensions,
                metadata=observation.metadata,
                tags=observation.tags,
            )
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = [list(item.embedding) for item in ordered]
        if len(vectors) != len(inputs):
            raise RuntimeError("OpenAI returned an unexpected number of embeddings.")
        if any(len(vector) != self.dimensions for vector in vectors):
            raise RuntimeError("OpenAI returned an embedding with unexpected dimensions.")
        return vectors


class EmbeddingInputTooLongError(ValueError):
    def __init__(self, *, input_index: int, token_count: int, max_tokens: int) -> None:
        self.input_index = input_index
        self.token_count = token_count
        self.max_tokens = max_tokens
        super().__init__(
            f"Embedding input {input_index} has {token_count} tokens; maximum is {max_tokens}."
        )


def build_embedder(
    provider: EmbeddingProvider,
    *,
    openai_api_key: str | None = None,
    openai_model: str = DEFAULT_OPENAI_EMBEDDING_MODEL,
    dimensions: int = DEFAULT_OPENAI_EMBEDDING_DIMENSIONS,
    timeout_seconds: float = 30.0,
    max_retries: int = 2,
) -> Embedder:
    if provider == "local":
        return LocalFeatureHashingEmbedder(dimensions=dimensions)
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for the OpenAI embedding provider.")
    return OpenAIEmbedder(
        api_key=openai_api_key,
        model_name=openai_model,
        dimensions=dimensions,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )


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


def _retryable_openai_error(exc: Exception) -> bool:
    return isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError)) or (
        isinstance(exc, APIStatusError) and exc.status_code >= 500
    )


def _response_model(response: Any, fallback: str) -> str:
    model = getattr(response, "model", None)
    return model if isinstance(model, str) and model else fallback


def _embedding_input_tokens(response: Any, *, fallback: int) -> int:
    usage = getattr(response, "usage", None)
    if usage is None:
        return fallback
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    if prompt_tokens is None and isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")
    try:
        return max(0, int(prompt_tokens if prompt_tokens is not None else fallback))
    except (TypeError, ValueError):
        return fallback
