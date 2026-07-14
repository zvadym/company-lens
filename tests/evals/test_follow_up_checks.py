from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from company_lens.evals.case_checks import evaluate_case
from company_lens.evals.golden import ExpectedBehavior, load_golden_dataset
from company_lens.evals.models import ObservedCaseResult
from tests.evals.follow_up_fixtures import follow_up_results


@pytest.mark.parametrize("case_index", [1, 2])
def test_follow_up_company_rules_accept_ticker_only_mentions(case_index: int) -> None:
    dataset = load_golden_dataset(Path("evals/datasets/golden/follow_up.v1.yaml"))
    payload = follow_up_results()["results"][case_index]
    for company in payload["companies"]:
        company["mention"] = company.pop("ticker").casefold()

    evaluation = evaluate_case(
        dataset.cases[case_index],
        ObservedCaseResult.model_validate(payload),
        gate=None,
    )

    assert evaluation.checks["companies"] is True
    assert evaluation.checks["follow_up_safety"] is True


def test_follow_up_dataset_defines_operations_to_inherit() -> None:
    dataset = load_golden_dataset(Path("evals/datasets/golden/follow_up.v1.yaml"))

    assert [case.expected.operation for case in dataset.cases] == [
        "quarter_over_quarter_growth",
        "quarter_over_quarter_growth",
        "quarter_over_quarter_growth",
        "year_over_year_growth",
    ]
    for case in dataset.cases:
        assert case.expected.follow_up is not None
        assert "operation" in case.expected.follow_up.inherit


def test_follow_up_cannot_inherit_an_unspecified_operation() -> None:
    dataset = load_golden_dataset(Path("evals/datasets/golden/follow_up.v1.yaml"))
    payload = dataset.cases[0].expected.model_dump(mode="python")
    payload["operation"] = None

    with pytest.raises(ValidationError, match="requires an expected operation"):
        ExpectedBehavior.model_validate(payload)
