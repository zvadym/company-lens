from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from company_lens.config import Settings

RerankStatus = Literal["disabled", "succeeded", "partial", "fallback", "failed"]


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


@dataclass(frozen=True)
class RerankDiagnostics:
    provider: str
    name: str
    status: RerankStatus
    candidate_count: int
    scored_count: int
    model: str | None = None
    latency_ms: float | None = None
    fallback_reason: str | None = None
    warnings: tuple[str, ...] = ()


class RerankerError(RuntimeError):
    """Sanitized reranker failure used for fail-closed retrieval mode."""


class Reranker(Protocol):
    name: str

    def rerank(self, items: tuple[RerankInput, ...]) -> tuple[RerankOutput, ...]:
        """Return replacement scores for the input items."""


class NoopReranker:
    name = "noop-reranker-v1"

    def __init__(self) -> None:
        self.last_diagnostics = RerankDiagnostics(
            provider="noop",
            name=self.name,
            status="disabled",
            candidate_count=0,
            scored_count=0,
        )

    def rerank(self, items: tuple[RerankInput, ...]) -> tuple[RerankOutput, ...]:
        self.last_diagnostics = RerankDiagnostics(
            provider="noop",
            name=self.name,
            status="disabled",
            candidate_count=len(items),
            scored_count=len(items),
        )
        return tuple(RerankOutput(chunk_id=item.chunk_id, score=item.score) for item in items)


class HttpReranker:
    name = "http-reranker-v1"

    def __init__(self, *, url: str, timeout_seconds: float, fail_closed: bool) -> None:
        self._url = url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._fail_closed = fail_closed
        self.last_diagnostics = RerankDiagnostics(
            provider="http",
            name=self.name,
            status="disabled",
            candidate_count=0,
            scored_count=0,
        )

    def rerank(self, items: tuple[RerankInput, ...]) -> tuple[RerankOutput, ...]:
        if not items:
            self.last_diagnostics = RerankDiagnostics(
                provider="http",
                name=self.name,
                status="succeeded",
                candidate_count=0,
                scored_count=0,
            )
            return ()
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(
                    f"{self._url}/rerank",
                    json={
                        "query": items[0].query,
                        "items": [{"id": item.chunk_id, "text": item.text} for item in items],
                    },
                )
                response.raise_for_status()
                payload = response.json()
            outputs, model, warnings = _parse_response(payload, items)
            status: RerankStatus = "partial" if len(outputs) < len(items) else "succeeded"
            if len(outputs) < len(items):
                outputs = _fill_missing_outputs(items, outputs)
            self.last_diagnostics = RerankDiagnostics(
                provider="http",
                name=self.name,
                status=status,
                model=model,
                candidate_count=len(items),
                scored_count=len(outputs),
                latency_ms=(time.perf_counter() - started) * 1000,
                warnings=warnings,
            )
            return outputs
        except RerankerError:
            raise
        except Exception:
            if self._fail_closed:
                self.last_diagnostics = RerankDiagnostics(
                    provider="http",
                    name=self.name,
                    status="failed",
                    candidate_count=len(items),
                    scored_count=0,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    fallback_reason="reranker_request_failed",
                    warnings=("reranker_request_failed",),
                )
                raise RerankerError("Reranker request failed.") from None
            self.last_diagnostics = RerankDiagnostics(
                provider="http",
                name=self.name,
                status="fallback",
                candidate_count=len(items),
                scored_count=0,
                latency_ms=(time.perf_counter() - started) * 1000,
                fallback_reason="reranker_request_failed",
                warnings=("reranker_request_failed",),
            )
            return tuple(RerankOutput(chunk_id=item.chunk_id, score=item.score) for item in items)


def build_reranker(settings: Settings) -> Reranker:
    if settings.reranker_provider == "noop":
        return NoopReranker()
    return HttpReranker(
        url=settings.reranker_url,
        timeout_seconds=settings.reranker_timeout_seconds,
        fail_closed=settings.reranker_fail_closed,
    )


def _parse_response(
    payload: Any,
    items: tuple[RerankInput, ...],
) -> tuple[tuple[RerankOutput, ...], str | None, tuple[str, ...]]:
    if not isinstance(payload, dict):
        raise ValueError("Reranker response must be an object.")
    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError("Reranker model must be a string.")
    scores = payload.get("scores")
    if not isinstance(scores, list):
        raise ValueError("Reranker scores must be a list.")

    valid_ids = {item.chunk_id for item in items}
    seen: set[str] = set()
    outputs: list[RerankOutput] = []
    warnings: list[str] = []
    for entry in scores:
        if not isinstance(entry, dict):
            warnings.append("invalid_score_entry")
            continue
        chunk_id = entry.get("id")
        score = entry.get("score")
        if not isinstance(chunk_id, str) or chunk_id not in valid_ids:
            warnings.append("unknown_score_id")
            continue
        if chunk_id in seen:
            warnings.append("duplicate_score_id")
            continue
        if not isinstance(score, int | float) or not math.isfinite(float(score)):
            warnings.append("invalid_score_value")
            continue
        seen.add(chunk_id)
        outputs.append(RerankOutput(chunk_id=chunk_id, score=float(score)))
    missing = valid_ids - seen
    if missing:
        warnings.append("missing_score_id")
    return tuple(outputs), model, tuple(dict.fromkeys(warnings))


def _fill_missing_outputs(
    items: tuple[RerankInput, ...],
    outputs: tuple[RerankOutput, ...],
) -> tuple[RerankOutput, ...]:
    by_id = {output.chunk_id: output for output in outputs}
    return tuple(
        by_id.get(item.chunk_id, RerankOutput(item.chunk_id, item.score)) for item in items
    )
