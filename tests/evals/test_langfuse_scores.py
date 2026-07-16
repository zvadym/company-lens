from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from company_lens.evals.langfuse_scores import ScoreConfigError, reconcile_score_configs
from company_lens.evals.score_contract import ScoreContract, ScoreDefinition


@dataclass
class RecordingScoreConfigsApi:
    calls: list[dict[str, Any]] = field(default_factory=list)
    fail_create: bool = False

    def get(self, *, page: int, limit: int) -> dict[str, Any]:
        return {"data": [], "meta": {"total_pages": page}}

    def create(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail_create:
            raise SdkError("invalid request")
        self.calls.append(kwargs)
        return {"id": f"config-{kwargs['name']}", **kwargs}


class SdkError(Exception):
    pass


class ApiClient:
    def __init__(self, score_configs: RecordingScoreConfigsApi) -> None:
        self.api = type("Api", (), {"score_configs": score_configs})()


def test_score_config_payload_omits_fields_that_do_not_apply() -> None:
    api = RecordingScoreConfigsApi()

    reconcile_score_configs(ApiClient(api), _contract())

    assert api.calls == [
        {
            "name": "boolean_score",
            "data_type": "BOOLEAN",
            "description": "Boolean score.",
        },
        {
            "name": "numeric_score",
            "data_type": "NUMERIC",
            "description": "Numeric score.",
            "min_value": 0.0,
            "max_value": 1.0,
        },
        {
            "name": "categorical_score",
            "data_type": "CATEGORICAL",
            "description": "Categorical score.",
            "categories": [
                {"label": "passed", "value": 0.0},
                {"label": "failed", "value": 1.0},
            ],
        },
    ]


def test_sdk_errors_are_normalized_at_the_adapter_boundary() -> None:
    api = RecordingScoreConfigsApi(fail_create=True)

    with pytest.raises(ScoreConfigError, match="score_config_reconciliation_failed") as raised:
        reconcile_score_configs(ApiClient(api), _contract())

    assert isinstance(raised.value.__cause__, SdkError)


def _contract() -> ScoreContract:
    common = {"scope": "item", "applicability": "always"}
    return ScoreContract(
        name="test-contract",
        version=1,
        evaluator_version="test-v1",
        scores=(
            ScoreDefinition(
                name="boolean_score",
                data_type="BOOLEAN",
                description="Boolean score.",
                **common,
            ),
            ScoreDefinition(
                name="numeric_score",
                data_type="NUMERIC",
                minimum=0,
                maximum=1,
                description="Numeric score.",
                **common,
            ),
            ScoreDefinition(
                name="categorical_score",
                data_type="CATEGORICAL",
                categories=("passed", "failed"),
                description="Categorical score.",
                **common,
            ),
        ),
    )
