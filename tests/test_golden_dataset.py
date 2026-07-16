from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from company_lens import cli
from company_lens.evals.golden import GoldenDataset, golden_dataset_summary, load_golden_dataset

GOLDEN_CORE_DATASET = Path("evals/datasets/golden/core.v1.yaml")
GOLDEN_FOLLOW_UP_DATASET = Path("evals/datasets/golden/follow_up.v1.yaml")
GOLDEN_DATASETS = (GOLDEN_CORE_DATASET, GOLDEN_FOLLOW_UP_DATASET)


@pytest.mark.parametrize("dataset_path", GOLDEN_DATASETS)
def test_golden_dataset_loads(dataset_path: Path) -> None:
    # Every authored golden slice should pass the same framework-neutral validation boundary.
    assert load_golden_dataset(dataset_path).cases


def test_follow_up_golden_dataset_loads() -> None:
    # This only checks validator-visible dataset shape, not runtime agent behaviour.
    dataset = load_golden_dataset(GOLDEN_FOLLOW_UP_DATASET)

    assert dataset.name == "company-lens-follow-up-golden"
    assert dataset.version == 1
    assert len(dataset.cases) == 4
    summary = golden_dataset_summary(dataset)
    assert summary["categories"] == {"follow_up": 4}
    assert summary["citation_modes"] == {"required": 3, "not_applicable": 1}
    assert all(case.category == "follow_up" for case in dataset.cases)
    assert all(
        len([turn for turn in case.conversation if turn.role == "user"]) >= 2
        for case in dataset.cases
    )


def test_foundation_golden_datasets_have_balanced_category_and_citation_coverage() -> None:
    dataset = load_golden_dataset(GOLDEN_CORE_DATASET)
    follow_up = load_golden_dataset(GOLDEN_FOLLOW_UP_DATASET)

    assert dataset.name == "company-lens-core-golden"
    assert len(dataset.cases) == 14
    all_cases = (*dataset.cases, *follow_up.cases)
    assert 18 <= len(all_cases) <= 25
    category_counts = {
        category: sum(case.category == category for case in all_cases)
        for category in {case.category for case in all_cases}
    }
    assert min(category_counts.values()) >= 2
    assert {case.citation_scenario for case in all_cases if case.citation_scenario} == {
        "valid",
        "missing_attempt",
        "unknown_evidence_attempt",
        "semantic_mismatch_attempt",
    }
    assert all(
        case.citation_mode == "required" for case in all_cases if case.citation_scenario is not None
    )


def test_unresolved_companies_cannot_define_tickers() -> None:
    # An unresolved company with a ticker would make the expected behaviour internally inconsistent.
    payload = {
        "name": "invalid-golden",
        "version": 1,
        "cases": [
            {
                "id": "followup_invalid_unresolved_ticker_001",
                "category": "follow_up",
                "conversation": [
                    {"role": "user", "content": "Show Netflix revenue growth."},
                    {"role": "user", "content": "Do the same for Globex."},
                ],
                "expected": {
                    "companies": [
                        {
                            "mention": "Globex",
                            "status": "unresolved",
                            "ticker": "GBX",
                            "source": "current_question",
                        }
                    ],
                    "metrics": ["revenue"],
                    "follow_up": {
                        "inherit": ["metrics"],
                        "prohibited_companies": ["Netflix"],
                        "must_not_reuse_previous_company": True,
                    },
                    "route": {"expected_route": "unsupported"},
                },
            }
        ],
    }

    with pytest.raises(ValidationError, match="unresolved companies must not define a ticker"):
        GoldenDataset.model_validate(payload)


def test_required_and_prohibited_tools_cannot_overlap() -> None:
    # The schema rejects impossible route expectations before evaluator work exists.
    payload = {
        "name": "invalid-golden",
        "version": 1,
        "cases": [
            {
                "id": "structured_invalid_tool_overlap_001",
                "category": "structured_financial",
                "conversation": [{"role": "user", "content": "What was NET revenue?"}],
                "expected": {
                    "companies": [
                        {
                            "mention": "Cloudflare",
                            "status": "resolved",
                            "ticker": "NET",
                            "source": "current_question",
                        }
                    ],
                    "metrics": ["revenue"],
                    "route": {
                        "expected_route": "structured_only",
                        "required_tools": ["query_financial_facts"],
                        "prohibited_tools": ["query_financial_facts"],
                    },
                },
            }
        ],
    }

    with pytest.raises(ValidationError, match="tools cannot be both required and prohibited"):
        GoldenDataset.model_validate(payload)


def test_cli_validates_golden_dataset(capsys: pytest.CaptureFixture[str]) -> None:
    # The CLI path is what CI and humans can run without importing Python internals.
    assert (
        cli.main(
            [
                "validate-golden-dataset",
                "--dataset",
                str(GOLDEN_CORE_DATASET),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert '"name": "company-lens-core-golden"' in output
    assert '"cases": 14' in output


def test_golden_loader_defaults_citation_mode_and_records_source_hash() -> None:
    dataset = load_golden_dataset(GOLDEN_CORE_DATASET)

    assert dataset.source_path == GOLDEN_CORE_DATASET
    assert dataset.content_hash is not None
    assert len(dataset.content_hash) == 64
    assert {case.citation_mode for case in dataset.cases} == {"required", "not_applicable"}


def test_golden_yaml_remains_framework_neutral() -> None:
    authored = "\n".join(path.read_text(encoding="utf-8").lower() for path in GOLDEN_DATASETS)

    assert "langfuse" not in authored
    assert "score_config" not in authored
    assert "dataset_run" not in authored


def test_golden_case_rejects_unknown_citation_scenario() -> None:
    payload = load_golden_dataset(GOLDEN_CORE_DATASET).model_dump(
        mode="json",
        exclude={"source_path", "content_hash"},
    )
    payload["cases"][0]["citation_scenario"] = "provider_specific_failure"

    with pytest.raises(ValidationError, match="citation_scenario"):
        GoldenDataset.model_validate(payload)
