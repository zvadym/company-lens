from __future__ import annotations

from opentelemetry import trace


def record_operation_reconciliation(
    *,
    required: bool,
    intent_operations: tuple[str, ...],
    conflict_reasons: tuple[str, ...],
    branch_count: int,
    decision_count: int,
    final_operations: tuple[str, ...],
    attempts: int,
    outcome: str,
) -> None:
    span = trace.get_current_span()
    span.set_attribute("company_lens.operation_reconciliation.required", required)
    span.set_attribute(
        "company_lens.operation_reconciliation.intent_operations",
        list(intent_operations),
    )
    span.set_attribute(
        "company_lens.operation_reconciliation.conflict_reasons",
        list(conflict_reasons),
    )
    span.set_attribute("company_lens.operation_reconciliation.branch_count", branch_count)
    span.set_attribute("company_lens.operation_reconciliation.decision_count", decision_count)
    span.set_attribute(
        "company_lens.operation_reconciliation.final_operations",
        list(final_operations),
    )
    span.set_attribute("company_lens.operation_reconciliation.attempts", attempts)
    span.set_attribute("company_lens.operation_reconciliation.outcome", outcome)


__all__ = ("record_operation_reconciliation",)
