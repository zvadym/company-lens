from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Literal
from weakref import WeakSet

from opentelemetry import metrics, trace
from opentelemetry.metrics import Counter, Histogram
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode

from company_lens.config import Settings
from company_lens.observability.context import current_context

logger = logging.getLogger(__name__)

_configured = False
_langfuse: Any | None = None
_operation_count: Counter | None = None
_operation_duration: Histogram | None = None
_token_count: Counter | None = None
_model_cost: Counter | None = None
_cache_access: Counter | None = None
_retrieval_results: Histogram | None = None
_validation_results: Counter | None = None
_instrumented_engines: WeakSet[Any] = WeakSet()

TraceContentPolicy = Literal["metadata", "redacted", "full"]
_REDACTED_PREVIEW_CHARS = 500
_REDACTED_COLLECTION_ITEMS = 20
_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[=:]\s*[^\s,;]+"),
    re.compile(r"(?i)(https?://[^:/\s]+:)[^@/\s]+@"),
)


@dataclass(frozen=True)
class EmbeddingObservationContext:
    metadata: Mapping[str, Any]
    tags: tuple[str, ...] = ()


_EMBEDDING_OBSERVATION_CONTEXT: ContextVar[EmbeddingObservationContext] = ContextVar(
    "company_lens_embedding_observation_context"
)


def configure_telemetry(settings: Settings) -> None:
    global _configured, _langfuse
    if _configured or not settings.telemetry_enabled:
        return
    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "service.version": settings.service_version,
            "deployment.environment.name": settings.environment,
            "company_lens.prompt.version": settings.prompt_version,
            "company_lens.parser.version": settings.parser_version,
            "company_lens.embedding.model": settings.openai_embedding_model,
            "company_lens.index.version": settings.agent_retrieval_index_version,
        }
    )
    readers: list[MetricReader] = []
    if settings.metrics_enabled:
        from opentelemetry.exporter.prometheus import PrometheusMetricReader

        readers.append(PrometheusMetricReader())
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))
    _initialize_instruments()

    if settings.langfuse_public_key and settings.langfuse_secret_key is not None:
        from langfuse import Langfuse

        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_base_url,
            environment=settings.environment,
            release=settings.service_version,
            should_export_span=_should_export_langfuse_span,
        )
        logger.info("Langfuse trace exporter configured", extra={"event": "telemetry.configured"})
    _configured = True


def instrument_fastapi(app: Any) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    if not getattr(app.state, "otel_instrumented", False):
        FastAPIInstrumentor.instrument_app(app)
        app.state.otel_instrumented = True


def instrument_sqlalchemy(engine: Any) -> None:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    if engine not in _instrumented_engines:
        SQLAlchemyInstrumentor().instrument(engine=engine)
        _instrumented_engines.add(engine)


def shutdown_telemetry() -> None:
    if _langfuse is not None:
        _langfuse.flush()


@contextmanager
def observe_operation(
    name: str,
    *,
    kind: str,
    attributes: Mapping[str, str | int | float | bool] | None = None,
) -> Iterator[trace.Span]:
    context = current_context()
    span_attributes: dict[str, str | int | float | bool] = {
        "company_lens.operation.kind": kind,
    }
    if context.correlation_id:
        span_attributes["company_lens.correlation_id"] = context.correlation_id
    if context.run_id:
        span_attributes["company_lens.run_id"] = context.run_id
    if context.session_id:
        span_attributes["company_lens.session_id"] = context.session_id
    if attributes:
        span_attributes.update(attributes)
    started = time.perf_counter()
    status = "success"
    with trace.get_tracer("company_lens").start_as_current_span(
        name, attributes=span_attributes
    ) as span:
        try:
            yield span
        except Exception as exc:
            status = "error"
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            metric_attributes = {"operation": name, "kind": kind, "status": status}
            if _operation_count is not None:
                _operation_count.add(1, metric_attributes)
            if _operation_duration is not None:
                _operation_duration.record(duration_ms, metric_attributes)


def record_model_usage(
    *, model: str, purpose: str, input_tokens: int, output_tokens: int, cost_usd: float = 0
) -> None:
    attributes = {"model": model, "purpose": purpose}
    if _token_count is not None:
        _token_count.add(input_tokens, {**attributes, "direction": "input"})
        _token_count.add(output_tokens, {**attributes, "direction": "output"})
    if _model_cost is not None and cost_usd:
        _model_cost.add(cost_usd, attributes)
    span = trace.get_current_span()
    span.set_attribute("gen_ai.request.model", model)
    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)


@contextmanager
def bind_embedding_observation(
    *,
    metadata: Mapping[str, Any],
    tags: tuple[str, ...] = (),
) -> Iterator[EmbeddingObservationContext]:
    token: Token[EmbeddingObservationContext] = _EMBEDDING_OBSERVATION_CONTEXT.set(
        EmbeddingObservationContext(metadata=metadata, tags=tags)
    )
    try:
        yield _EMBEDDING_OBSERVATION_CONTEXT.get()
    finally:
        _EMBEDDING_OBSERVATION_CONTEXT.reset(token)


def current_embedding_observation() -> EmbeddingObservationContext:
    try:
        return _EMBEDDING_OBSERVATION_CONTEXT.get()
    except LookupError:
        return EmbeddingObservationContext(metadata={})


def record_embedding(
    *,
    model: str,
    input_tokens: int,
    input_count: int,
    dimensions: int,
    metadata: Mapping[str, Any] | None = None,
    tags: tuple[str, ...] = (),
) -> None:
    record_model_usage(
        model=model,
        purpose="embedding",
        input_tokens=input_tokens,
        output_tokens=0,
    )
    span = trace.get_current_span()
    usage_details = {"input": input_tokens}
    embedding_metadata: dict[str, Any] = {
        "purpose": "embedding",
        "input_count": input_count,
        "dimensions": dimensions,
    }
    if metadata:
        embedding_metadata.update(metadata)

    span.set_attribute("gen_ai.usage.total_tokens", input_tokens)
    span.set_attribute("company_lens.embedding.input_count", input_count)
    span.set_attribute("company_lens.embedding.dimensions", dimensions)
    if tags:
        span.set_attribute("langfuse.trace.tags", list(tags))

    langfuse_attributes = _langfuse_embedding_attributes(
        model=model,
        usage_details=usage_details,
        metadata=embedding_metadata,
    )
    for key, value in langfuse_attributes.items():
        span.set_attribute(key, value)


def record_generation(
    *,
    model: str,
    purpose: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    trace_content: TraceContentPolicy,
    input_payload: Any | None = None,
    output_payload: Any | None = None,
    response_id: str | None = None,
    model_parameters: Mapping[str, str | int | float | bool] | None = None,
    tags: tuple[str, ...] = (),
    cost_usd: float = 0,
) -> None:
    record_model_usage(
        model=model,
        purpose=purpose,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    span = trace.get_current_span()
    usage_details = {
        "input": input_tokens,
        "output": output_tokens,
        "total": total_tokens,
    }
    span.set_attribute("gen_ai.usage.total_tokens", total_tokens)
    if tags:
        span.set_attribute("langfuse.trace.tags", list(tags))
    langfuse_attributes = _langfuse_generation_attributes(
        model=model,
        purpose=purpose,
        usage_details=usage_details,
        trace_content=trace_content,
        input_payload=input_payload,
        output_payload=output_payload,
        response_id=response_id,
        model_parameters=model_parameters,
    )
    for key, value in langfuse_attributes.items():
        span.set_attribute(key, value)


def record_cache_access(*, cache: str, hits: int, misses: int) -> None:
    if _cache_access is not None:
        _cache_access.add(hits, {"cache": cache, "result": "hit"})
        _cache_access.add(misses, {"cache": cache, "result": "miss"})
    span = trace.get_current_span()
    span.set_attribute("company_lens.cache.hits", hits)
    span.set_attribute("company_lens.cache.misses", misses)


def record_retrieval(*, strategy: str, result_count: int, context_count: int) -> None:
    if _retrieval_results is not None:
        _retrieval_results.record(result_count, {"strategy": strategy, "stage": "retrieved"})
        _retrieval_results.record(context_count, {"strategy": strategy, "stage": "context"})
    span = trace.get_current_span()
    span.set_attribute("company_lens.retrieval.result_count", result_count)
    span.set_attribute("company_lens.retrieval.context_count", context_count)


def record_validation(*, validator: str, valid: bool, issue_count: int) -> None:
    if _validation_results is not None:
        _validation_results.add(
            1,
            {"validator": validator, "result": "valid" if valid else "invalid"},
        )
    span = trace.get_current_span()
    span.set_attribute("company_lens.validation.valid", valid)
    span.set_attribute("company_lens.validation.issue_count", issue_count)


def _initialize_instruments() -> None:
    global _operation_count, _operation_duration, _token_count, _model_cost
    global _cache_access, _retrieval_results, _validation_results
    meter = metrics.get_meter("company_lens")
    _operation_count = meter.create_counter("company_lens.operation.count")
    _operation_duration = meter.create_histogram("company_lens.operation.duration", unit="ms")
    _token_count = meter.create_counter("company_lens.model.tokens")
    _model_cost = meter.create_counter("company_lens.model.cost", unit="USD")
    _cache_access = meter.create_counter("company_lens.cache.access")
    _retrieval_results = meter.create_histogram("company_lens.retrieval.results")
    _validation_results = meter.create_counter("company_lens.validation.count")


def _should_export_langfuse_span(span: Any) -> bool:
    attributes = getattr(span, "attributes", None)
    if not isinstance(attributes, Mapping):
        return False
    if any(str(key).startswith("langfuse.") for key in attributes):
        return True
    kind = attributes.get("company_lens.operation.kind")
    if kind in {"model", "embedding"}:
        return True
    return bool(attributes.get("gen_ai.system"))


def _langfuse_generation_attributes(
    *,
    model: str,
    purpose: str,
    usage_details: Mapping[str, int],
    trace_content: TraceContentPolicy,
    input_payload: Any | None,
    output_payload: Any | None,
    response_id: str | None,
    model_parameters: Mapping[str, str | int | float | bool] | None,
) -> dict[str, str]:
    try:
        from langfuse import LangfuseOtelSpanAttributes
    except ImportError:
        return {}

    metadata: dict[str, str] = {
        "purpose": purpose,
        "trace_content": trace_content,
    }
    if response_id:
        metadata["response_id"] = response_id

    attributes = {
        LangfuseOtelSpanAttributes.OBSERVATION_TYPE: "generation",
        LangfuseOtelSpanAttributes.OBSERVATION_MODEL: model,
        LangfuseOtelSpanAttributes.OBSERVATION_USAGE_DETAILS: _json_attribute(usage_details),
        LangfuseOtelSpanAttributes.OBSERVATION_METADATA: _json_attribute(metadata),
    }
    if model_parameters:
        attributes[LangfuseOtelSpanAttributes.OBSERVATION_MODEL_PARAMETERS] = _json_attribute(
            model_parameters
        )
    if trace_content != "metadata":
        attributes[LangfuseOtelSpanAttributes.OBSERVATION_INPUT] = _json_attribute(
            _content_payload(input_payload, trace_content)
        )
        attributes[LangfuseOtelSpanAttributes.OBSERVATION_OUTPUT] = _json_attribute(
            _content_payload(output_payload, trace_content)
        )
    return attributes


def _langfuse_embedding_attributes(
    *,
    model: str,
    usage_details: Mapping[str, int],
    metadata: Mapping[str, Any],
) -> dict[str, str]:
    try:
        from langfuse import LangfuseOtelSpanAttributes
    except ImportError:
        return {}

    return {
        LangfuseOtelSpanAttributes.OBSERVATION_TYPE: "embedding",
        LangfuseOtelSpanAttributes.OBSERVATION_MODEL: model,
        LangfuseOtelSpanAttributes.OBSERVATION_USAGE_DETAILS: _json_attribute(usage_details),
        LangfuseOtelSpanAttributes.OBSERVATION_METADATA: _json_attribute(metadata),
    }


def _content_payload(value: Any, trace_content: TraceContentPolicy) -> Any:
    if trace_content == "full":
        return value
    if trace_content == "redacted":
        return _redacted_payload(value)
    return None


def _redacted_payload(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return {
            "preview": _redact_text(value[:_REDACTED_PREVIEW_CHARS]),
            "chars": len(value),
            "truncated": len(value) > _REDACTED_PREVIEW_CHARS,
        }
    if isinstance(value, Mapping):
        return {
            str(key): _redacted_payload(item)
            for key, item in list(value.items())[:_REDACTED_COLLECTION_ITEMS]
        }
    if isinstance(value, (list, tuple)):
        return [_redacted_payload(item) for item in value[:_REDACTED_COLLECTION_ITEMS]]
    if isinstance(value, (int, float, bool)):
        return value
    return {
        "preview": _redact_text(str(value)[:_REDACTED_PREVIEW_CHARS]),
        "chars": len(str(value)),
        "truncated": len(str(value)) > _REDACTED_PREVIEW_CHARS,
    }


def _redact_text(value: str) -> str:
    redacted = _SECRET_PATTERNS[0].sub("[REDACTED]", value)
    redacted = _SECRET_PATTERNS[1].sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return _SECRET_PATTERNS[2].sub(r"\1[REDACTED]@", redacted)


def _json_attribute(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
