from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from company_lens.agent.calculation_intents import (
    BranchOperationDecision,
    CalculationIntent,
    ModelCalculationIntent,
    OperationReconciliation,
    domain_calculation_intent,
)


@pytest.mark.parametrize(
    ("operation", "parameters"),
    [
        ("quarter_over_quarter_growth", {}),
        ("year_over_year_growth", {}),
        ("cagr", {"years": 3.5}),
        ("margin", {}),
        ("absolute_change", {}),
        ("percentage_change", {}),
        ("rolling_average", {"window": 4}),
        ("normalised_index", {"base": 100.0}),
        ("correlation", {}),
    ],
)
def test_model_intents_support_every_operation_with_applicable_scalars(
    operation: str,
    parameters: dict[str, float | int],
) -> None:
    intent = ModelCalculationIntent(
        operation=operation,
        metrics=("revenue", "operating_income") if operation == "margin" else ("revenue",),
        **parameters,
    )

    domain = domain_calculation_intent(intent)

    assert domain.operation == operation
    assert domain.years == (Decimal("3.5") if operation == "cagr" else None)
    assert domain.base == (Decimal("100.0") if operation == "normalised_index" else None)


@pytest.mark.parametrize(
    ("operation", "parameters"),
    [
        ("quarter_over_quarter_growth", {"window": 8}),
        ("rolling_average", {}),
        ("rolling_average", {"years": 2.0, "window": 4}),
        ("cagr", {}),
        ("cagr", {"years": 2.0, "base": 100.0}),
        ("percentage_change", {"base": 100.0}),
    ],
)
def test_model_intents_reject_missing_or_inapplicable_scalars(
    operation: str,
    parameters: dict[str, float | int],
) -> None:
    with pytest.raises(ValidationError):
        ModelCalculationIntent(operation=operation, metrics=("revenue",), **parameters)


def test_source_period_is_not_a_calculation_window() -> None:
    with pytest.raises(ValidationError):
        CalculationIntent(
            operation="quarter_over_quarter_growth",
            metrics=("revenue",),
            window=8,
        )


def test_metrics_are_normalized_and_unique() -> None:
    intent = CalculationIntent(
        operation="margin",
        metrics=(" operating_income ", "revenue"),
    )

    assert intent.metrics == ("operating_income", "revenue")
    with pytest.raises(ValidationError):
        CalculationIntent(
            operation="margin",
            metrics=("revenue", " revenue "),
        )


def test_reconciliation_schema_uses_json_numbers_and_nullable_scalars() -> None:
    schema = OperationReconciliation.model_json_schema()
    decision = schema["$defs"]["BranchOperationDecision"]

    assert {item.get("type") for item in decision["properties"]["years"]["anyOf"]} == {
        "number",
        "null",
    }
    assert {item.get("type") for item in decision["properties"]["base"]["anyOf"]} == {
        "number",
        "null",
    }


def test_decision_scalar_rules_match_the_selected_operation() -> None:
    reconciliation = OperationReconciliation(
        branch_operations=(
            BranchOperationDecision(
                branch_id="rolling_revenue",
                operation="rolling_average",
                window=4,
            ),
        )
    )

    assert reconciliation.branch_operations[0].window == 4
    with pytest.raises(ValidationError):
        BranchOperationDecision(
            branch_id="qoq_revenue",
            operation="quarter_over_quarter_growth",
            window=8,
        )
