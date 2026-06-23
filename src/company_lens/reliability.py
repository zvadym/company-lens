from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from company_lens.observability.telemetry import observe_operation

logger = logging.getLogger(__name__)


class CircuitOpenError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_delay_seconds: float = 0.25
    maximum_delay_seconds: float = 5.0
    multiplier: float = 2.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one.")
        if self.initial_delay_seconds < 0 or self.maximum_delay_seconds < 0:
            raise ValueError("Retry delays cannot be negative.")
        if self.multiplier < 1:
            raise ValueError("Retry multiplier must be at least one.")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between zero and one.")

    def delay(self, attempt: int, *, random_value: float | None = None) -> float:
        base = min(
            self.maximum_delay_seconds,
            self.initial_delay_seconds * self.multiplier ** max(0, attempt - 1),
        )
        jitter = base * self.jitter_ratio
        sample = random.random() if random_value is None else random_value
        return max(0, base - jitter + (2 * jitter * sample))


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 5, recovery_seconds: float = 30.0) -> None:
        if failure_threshold < 1 or recovery_seconds <= 0:
            raise ValueError("Circuit breaker limits must be positive.")
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_call = False
        self._lock = threading.Lock()

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if time.monotonic() - self._opened_at < self._recovery_seconds:
                raise CircuitOpenError("External service circuit is open.")
            if self._half_open_call:
                raise CircuitOpenError("External service circuit is half-open.")
            self._half_open_call = True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_call = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._half_open_call = False
            if self._failures >= self._failure_threshold:
                self._opened_at = time.monotonic()

    def record_ignored_failure(self) -> None:
        with self._lock:
            self._half_open_call = False


def call_with_resilience[T](
    operation: Callable[[], T],
    *,
    provider: str,
    retry_policy: RetryPolicy,
    circuit_breaker: CircuitBreaker,
    retry_if: Callable[[Exception], bool],
    sleeper: Callable[[float], None] = time.sleep,
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, retry_policy.max_attempts + 1):
        circuit_breaker.before_call()
        try:
            with observe_operation(
                f"external.{provider}",
                kind="external_request",
                attributes={"server.address": provider, "company_lens.retry.attempt": attempt},
            ):
                result = operation()
            circuit_breaker.record_success()
            return result
        except CircuitOpenError:
            raise
        except Exception as exc:
            last_error = exc
            retryable = retry_if(exc)
            if retryable:
                circuit_breaker.record_failure()
            else:
                circuit_breaker.record_ignored_failure()
            logger.warning(
                "External operation failed",
                extra={
                    "event": "external.retry",
                    "provider": provider,
                    "attempt": attempt,
                    "status": "retrying" if retryable else "failed",
                },
            )
            if not retryable or attempt >= retry_policy.max_attempts:
                raise
            sleeper(retry_policy.delay(attempt))
    if last_error is not None:  # pragma: no cover - the loop always raises or returns
        raise last_error
    raise RuntimeError("Retry loop completed without a result.")  # pragma: no cover
