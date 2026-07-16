from __future__ import annotations

import pytest
from pydantic import ValidationError

from company_lens.evals.gates import EvaluationGate, OperationalBudget
from company_lens.evals.models import ObservedCaseResult, ObservedOperationalMetrics
from company_lens.evals.operational_checks import check_operational_budgets


def test_api_call_budget_applies_to_each_whole_case_attempt() -> None:
    observed = _observed(api_calls=16, case_attempts=2)
    failures: list[str] = []

    passed = check_operational_budgets(observed, _gate(), failures)

    assert passed is True
    assert failures == []


@pytest.mark.parametrize(
    ("api_calls", "case_attempts", "expected_maximum"),
    ((11, 1, 10), (21, 2, 20)),
)
def test_api_call_budget_remains_strict_with_and_without_replay(
    api_calls: int,
    case_attempts: int,
    expected_maximum: int,
) -> None:
    observed = _observed(api_calls=api_calls, case_attempts=case_attempts)
    failures: list[str] = []

    passed = check_operational_budgets(observed, _gate(), failures)

    assert passed is False
    assert failures == [f"API calls was {api_calls}, expected at most {expected_maximum}"]


def test_case_attempts_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        ObservedOperationalMetrics(case_attempts=0)


def _observed(*, api_calls: int, case_attempts: int) -> ObservedCaseResult:
    return ObservedCaseResult(
        case_id="structured_example_revenue_001",
        operational=ObservedOperationalMetrics(
            api_calls=api_calls,
            retry_count=case_attempts - 1,
            case_attempts=case_attempts,
        ),
    )


def _gate() -> EvaluationGate:
    return EvaluationGate(
        name="operational-test",
        version=1,
        operational_budgets=OperationalBudget(max_api_calls=10),
    )
