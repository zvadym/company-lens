from __future__ import annotations

from pathlib import Path

from company_lens.evals.golden import GoldenDatasetCase, load_golden_dataset
from company_lens.evals.langfuse_experiment import run_dataset_experiment
from company_lens.evals.langfuse_sync import sync_dataset
from company_lens.evals.models import CaseObservation, CitationObservation
from company_lens.evals.score_contract import load_score_contract
from tests.evals.fakes_langfuse import FakeLangfuse

CORE = Path("evals/datasets/golden/core.v1.yaml")
SCORES = Path("evals/score-contracts/foundation.v1.yaml")


def test_experiment_publishes_deterministic_item_and_trusted_run_scores() -> None:
    client = FakeLangfuse()
    dataset = load_golden_dataset(CORE)
    contract = load_score_contract(SCORES)
    synced = sync_dataset(
        client,
        dataset,
        contract,
        expected_project_id="project-testing",
    )
    selected = dataset.cases[:1]

    run = run_dataset_experiment(
        client,
        client.get_dataset(dataset.name, version=synced.snapshot.version_timestamp),
        dataset,
        selected,
        snapshot=synced.snapshot,
        execution_id="11111111-1111-1111-1111-111111111111",
        commit_sha="abcdef1",
        manifest_fingerprint="a" * 64,
        score_contract=contract,
        score_bindings=synced.score_configs,
        execute_case=_passing_observation,
    )

    assert run.status == "completed"
    assert run.gate_status == "passed"
    assert run.langfuse_dataset_run_id == "run-1"
    assert run.langfuse_run_url == "https://langfuse.test/run/run-1"
    assert run.case_results[0].scores["case_pass"] is True
    assert run.case_results[0].scores["citation_valid"] is True
    assert all(score["config_id"] for score in client.scores.values())
    assert client.counters.flushes == 1


def test_infrastructure_observation_suppresses_aggregates_and_marks_run_not_evaluated() -> None:
    client = FakeLangfuse()
    dataset = load_golden_dataset(CORE)
    contract = load_score_contract(SCORES)
    synced = sync_dataset(
        client,
        dataset,
        contract,
        expected_project_id="project-testing",
    )

    run = run_dataset_experiment(
        client,
        client.get_dataset(dataset.name, version=synced.snapshot.version_timestamp),
        dataset,
        dataset.cases[:1],
        snapshot=synced.snapshot,
        execution_id="22222222-2222-2222-2222-222222222222",
        commit_sha="abcdef1",
        manifest_fingerprint="b" * 64,
        score_contract=contract,
        score_bindings=synced.score_configs,
        execute_case=lambda case: CaseObservation(
            case_id=case.id,
            outcome="infrastructure_error",
            failure_code="agent_execution_failed",
            citation=CitationObservation(
                mode=case.citation_mode,
                answer_present=False,
                validation_present=False,
            ),
        ),
    )

    assert run.status == "partial"
    assert run.gate_status == "not_evaluated"
    assert run.aggregate_scores == {}
    assert run.case_results[0].passed is None
    run_scores = [score for score in client.scores.values() if score.get("dataset_run_id")]
    assert [(score["name"], score["value"]) for score in run_scores] == [
        ("gate_status", "not_evaluated")
    ]


def _passing_observation(case: GoldenDatasetCase) -> CaseObservation:
    return CaseObservation(
        case_id=case.id,
        outcome="observed",
        companies=tuple(
            {
                "mention": company.mention,
                "status": company.status,
                "ticker": company.ticker,
                "source": company.source,
            }
            for company in case.expected.companies
        ),
        metrics=case.expected.metrics,
        operation=case.expected.operation,
        route=case.expected.route.expected_route,
        tools=case.expected.route.required_tools,
        citation=CitationObservation(
            mode=case.citation_mode,
            answer_present=True,
            validation_present=case.citation_mode == "required",
            valid=True if case.citation_mode == "required" else None,
        ),
    )
