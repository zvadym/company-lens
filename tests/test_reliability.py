from __future__ import annotations

import pytest

from company_lens.reliability import (
    CircuitBreaker,
    CircuitOpenError,
    RetryPolicy,
    call_with_resilience,
)


def test_retry_policy_uses_bounded_exponential_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("temporary")
        return "ok"

    result = call_with_resilience(
        operation,
        provider="test",
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_delay_seconds=0.1,
            maximum_delay_seconds=1,
            jitter_ratio=0,
        ),
        circuit_breaker=CircuitBreaker(failure_threshold=5),
        retry_if=lambda error: isinstance(error, TimeoutError),
        sleeper=delays.append,
    )

    assert result == "ok"
    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_circuit_breaker_opens_after_bounded_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=60)
    policy = RetryPolicy(max_attempts=1)

    for _ in range(2):
        with pytest.raises(TimeoutError):
            call_with_resilience(
                lambda: (_ for _ in ()).throw(TimeoutError("temporary")),
                provider="test",
                retry_policy=policy,
                circuit_breaker=breaker,
                retry_if=lambda _error: True,
            )

    with pytest.raises(CircuitOpenError):
        call_with_resilience(
            lambda: "unreachable",
            provider="test",
            retry_policy=policy,
            circuit_breaker=breaker,
            retry_if=lambda _error: True,
        )
