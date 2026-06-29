from __future__ import annotations

import io
import json
import logging

from langfuse import LangfuseOtelSpanAttributes

from company_lens.observability import telemetry
from company_lens.observability.context import bind_context
from company_lens.observability.logging import JsonFormatter
from company_lens.observability.telemetry import (
    ModelUsageRecord,
    collect_model_usage,
    record_embedding,
    record_generation,
)


def test_json_logs_include_bound_correlation_and_run_ids() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("company_lens.test.context")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    with bind_context(correlation_id="request-1", run_id="run-1", session_id="session-1"):
        logger.info(
            "completed api_key=secret-value sk-123456789 password=hunter2",
            extra={"event": "test.completed"},
        )

    payload = json.loads(stream.getvalue())
    assert payload["correlation_id"] == "request-1"
    assert payload["run_id"] == "run-1"
    assert payload["session_id"] == "session-1"
    assert payload["event"] == "test.completed"
    assert "secret-value" not in payload["message"]
    assert "sk-123456789" not in payload["message"]
    assert "hunter2" not in payload["message"]


def test_generation_trace_content_metadata_omits_raw_input_and_output(monkeypatch) -> None:
    span = _FakeSpan()
    _disable_generation_metrics(monkeypatch)
    monkeypatch.setattr(telemetry.trace, "get_current_span", lambda *_args, **_kwargs: span)

    record_generation(
        model="gpt-test",
        purpose="answer",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        trace_content="metadata",
        input_payload={"prompt": "secret prompt"},
        output_payload="secret output",
        response_id="resp_1",
    )

    assert span.attributes[LangfuseOtelSpanAttributes.OBSERVATION_TYPE] == "generation"
    assert span.attributes[LangfuseOtelSpanAttributes.OBSERVATION_MODEL] == "gpt-test"
    assert LangfuseOtelSpanAttributes.OBSERVATION_INPUT not in span.attributes
    assert LangfuseOtelSpanAttributes.OBSERVATION_OUTPUT not in span.attributes


def test_generation_observation_records_trace_tags(monkeypatch) -> None:
    span = _FakeSpan()
    _disable_generation_metrics(monkeypatch)
    monkeypatch.setattr(telemetry.trace, "get_current_span", lambda *_args, **_kwargs: span)

    record_generation(
        model="gpt-test",
        purpose="answer",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        trace_content="metadata",
        tags=("llm", "openai", "answer"),
    )

    assert span.attributes[LangfuseOtelSpanAttributes.TRACE_TAGS] == [
        "llm",
        "openai",
        "answer",
    ]


def test_generation_trace_content_redacted_records_preview_without_secrets(monkeypatch) -> None:
    span = _FakeSpan()
    _disable_generation_metrics(monkeypatch)
    monkeypatch.setattr(telemetry.trace, "get_current_span", lambda *_args, **_kwargs: span)

    record_generation(
        model="gpt-test",
        purpose="answer",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        trace_content="redacted",
        input_payload={"prompt": "api_key=secret-value " + ("x" * 600)},
        output_payload="sk-123456789 " + ("answer " * 100),
        response_id="resp_1",
    )

    trace_input = span.attributes[LangfuseOtelSpanAttributes.OBSERVATION_INPUT]
    trace_output = span.attributes[LangfuseOtelSpanAttributes.OBSERVATION_OUTPUT]
    assert "secret-value" not in trace_input
    assert "sk-123456789" not in trace_output
    assert "[REDACTED]" in trace_input
    assert "truncated" in trace_output


def test_generation_trace_content_full_records_payload(monkeypatch) -> None:
    span = _FakeSpan()
    _disable_generation_metrics(monkeypatch)
    monkeypatch.setattr(telemetry.trace, "get_current_span", lambda *_args, **_kwargs: span)

    record_generation(
        model="gpt-test",
        purpose="answer",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        trace_content="full",
        input_payload={"prompt": "full prompt"},
        output_payload="full answer",
        response_id="resp_1",
    )

    assert "full prompt" in span.attributes[LangfuseOtelSpanAttributes.OBSERVATION_INPUT]
    assert "full answer" in span.attributes[LangfuseOtelSpanAttributes.OBSERVATION_OUTPUT]


def test_embedding_observation_records_usage_without_static_cost(monkeypatch) -> None:
    span = _FakeSpan()
    _disable_generation_metrics(monkeypatch)
    monkeypatch.setattr(telemetry.trace, "get_current_span", lambda *_args, **_kwargs: span)

    record_embedding(
        model="text-embedding-3-small",
        input_tokens=123,
        input_count=2,
        dimensions=384,
        metadata={"company_name": "Cloudflare", "ticker": "NET"},
        tags=("embedding", "indexing", "openai"),
    )

    assert span.attributes[LangfuseOtelSpanAttributes.OBSERVATION_TYPE] == "embedding"
    assert span.attributes[LangfuseOtelSpanAttributes.OBSERVATION_MODEL] == (
        "text-embedding-3-small"
    )
    assert '"input": 123' in span.attributes[LangfuseOtelSpanAttributes.OBSERVATION_USAGE_DETAILS]
    assert "Cloudflare" in span.attributes[LangfuseOtelSpanAttributes.OBSERVATION_METADATA]
    assert span.attributes[LangfuseOtelSpanAttributes.TRACE_TAGS] == [
        "embedding",
        "indexing",
        "openai",
    ]
    assert LangfuseOtelSpanAttributes.OBSERVATION_COST_DETAILS not in span.attributes


def test_model_usage_collector_captures_generation_and_embedding(monkeypatch) -> None:
    span = _FakeSpan()
    _disable_generation_metrics(monkeypatch)
    monkeypatch.setattr(telemetry.trace, "get_current_span", lambda *_args, **_kwargs: span)

    with collect_model_usage() as records:
        record_generation(
            model="gpt-test",
            purpose="answer",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            trace_content="metadata",
            cost_usd=0.01,
        )
        record_embedding(
            model="text-embedding-3-small",
            input_tokens=123,
            input_count=2,
            dimensions=384,
        )

    assert records == [
        ModelUsageRecord(
            model="gpt-test",
            purpose="answer",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            cost_usd=0.01,
        ),
        ModelUsageRecord(
            model="text-embedding-3-small",
            purpose="embedding",
            input_tokens=123,
            output_tokens=0,
            total_tokens=123,
        ),
    ]


def test_langfuse_export_filter_keeps_meaningful_observations_and_drops_noise() -> None:
    assert telemetry._should_export_langfuse_span(  # noqa: SLF001
        _FakeReadableSpan({LangfuseOtelSpanAttributes.OBSERVATION_TYPE: "generation"})
    )
    assert telemetry._should_export_langfuse_span(  # noqa: SLF001
        _FakeReadableSpan({"company_lens.operation.kind": "model"})
    )
    assert not telemetry._should_export_langfuse_span(  # noqa: SLF001
        _FakeReadableSpan({"db.system": "postgresql", "db.statement": "SELECT 1"})
    )
    assert not telemetry._should_export_langfuse_span(  # noqa: SLF001
        _FakeReadableSpan({"http.method": "GET", "http.route": "/api/v1/health"})
    )


class _FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


class _FakeReadableSpan:
    def __init__(self, attributes: dict[str, object]) -> None:
        self.attributes = attributes


def _disable_generation_metrics(monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "_token_count", None)
    monkeypatch.setattr(telemetry, "_model_cost", None)
