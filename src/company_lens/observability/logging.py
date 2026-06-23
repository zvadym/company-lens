from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from company_lens.observability.context import current_context


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact(record.getMessage()),
        }
        context = current_context()
        payload["correlation_id"] = context.correlation_id
        payload["run_id"] = context.run_id
        payload["session_id"] = context.session_id
        for key in ("event", "operation", "provider", "attempt", "status", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = _redact(self.formatException(record.exc_info))
        return json.dumps(payload)


_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[=:]\s*[^\s,;]+"),
    re.compile(r"(?i)(https?://[^:/\s]+:)[^@/\s]+@"),
)


def _redact(value: str) -> str:
    redacted = _SECRET_PATTERNS[0].sub("[REDACTED]", value)
    redacted = _SECRET_PATTERNS[1].sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return _SECRET_PATTERNS[2].sub(r"\1[REDACTED]@", redacted)


def configure_logging(level: str) -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
