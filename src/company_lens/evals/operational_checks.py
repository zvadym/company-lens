from __future__ import annotations

from company_lens.evals.gates import EvaluationGate, OperationalBudget
from company_lens.evals.models import ObservedCaseResult


def operational_checks_enabled(
    observed: ObservedCaseResult,
    gate: EvaluationGate | None,
) -> bool:
    if observed.operational is not None:
        return True
    return bool(
        gate is not None
        and (gate.require_operational_metrics or gate.operational_budgets.configured())
    )


def check_operational_budgets(
    observed: ObservedCaseResult,
    gate: EvaluationGate | None,
    failures: list[str],
) -> bool:
    operational = observed.operational
    if operational is None:
        failures.append("missing operational metrics")
        return False

    passed = True
    budget = gate.operational_budgets if gate is not None else OperationalBudget()
    passed &= _check_maximum(
        "total latency",
        operational.total_latency_ms,
        budget.max_total_latency_ms,
        "ms",
        failures,
    )
    passed &= _check_maximum(
        "time to first event",
        operational.time_to_first_event_ms,
        budget.max_time_to_first_event_ms,
        "ms",
        failures,
    )
    passed &= _check_maximum(
        "tool calls",
        operational.tool_calls_used,
        _explicit_or_policy(budget.max_tool_calls, operational.policy_max_tool_calls),
        "",
        failures,
    )
    passed &= _check_maximum(
        "repair attempts",
        operational.repair_attempts,
        _explicit_or_policy(
            budget.max_repair_attempts,
            operational.policy_max_repair_attempts,
        ),
        "",
        failures,
    )
    passed &= _check_maximum("API calls", operational.api_calls, budget.max_api_calls, "", failures)
    passed &= _check_maximum(
        "retry count", operational.retry_count, budget.max_retry_count, "", failures
    )
    passed &= _check_maximum(
        "total tokens", operational.total_tokens, budget.max_total_tokens, "", failures
    )
    passed &= _check_maximum("cost", operational.cost_usd, budget.max_cost_usd, " USD", failures)
    if budget.max_node_latency_ms is not None:
        if not operational.node_latencies:
            failures.append("missing node latency metrics")
            passed = False
        for item in operational.node_latencies:
            passed &= _check_maximum(
                f"node {item.node} latency",
                item.duration_ms,
                budget.max_node_latency_ms,
                "ms",
                failures,
            )
    if operational.policy_max_retries_per_node is not None:
        for attempt in operational.node_attempts:
            allowed_attempts = operational.policy_max_retries_per_node + 1
            if attempt.attempts > allowed_attempts:
                failures.append(
                    f"node {attempt.node} attempts were {attempt.attempts}, "
                    f"expected at most {allowed_attempts}"
                )
                passed = False
    return passed


def _check_maximum(
    label: str,
    actual: int | float | None,
    maximum: int | float | None,
    unit: str,
    failures: list[str],
) -> bool:
    if maximum is None:
        return True
    if actual is None:
        failures.append(f"missing {label} metric")
        return False
    if actual <= maximum:
        return True
    failures.append(f"{label} was {actual}{unit}, expected at most {maximum}{unit}")
    return False


def _explicit_or_policy(
    explicit: int | float | None,
    policy: int | float | None,
) -> int | float | None:
    return explicit if explicit is not None else policy
