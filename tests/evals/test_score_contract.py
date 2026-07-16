from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from company_lens.evals.score_contract import ScoreContract, load_score_contract

SCORE_CONTRACT = Path("evals/score-contracts/foundation.v1.yaml")


def test_foundation_score_contract_is_unique_and_canonical() -> None:
    contract = load_score_contract(SCORE_CONTRACT)

    assert contract.evaluator_version == "foundation-deterministic-v1"
    assert len(contract.content_hash) == 64
    assert len({score.name for score in contract.scores}) == len(contract.scores)
    assert {score.name for score in contract.scores} >= {
        "case_pass",
        "citation_valid",
        "case_pass_rate",
        "gate_status",
    }


def test_score_contract_rejects_duplicate_names() -> None:
    score = {
        "name": "case_pass",
        "scope": "item",
        "data_type": "BOOLEAN",
        "applicability": "always",
        "description": "Case pass.",
    }
    with pytest.raises(ValidationError, match="duplicate score names"):
        ScoreContract.model_validate(
            {
                "name": "duplicate-contract",
                "version": 1,
                "evaluator_version": "v1",
                "scores": [score, score],
            }
        )
