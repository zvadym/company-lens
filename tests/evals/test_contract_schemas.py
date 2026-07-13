from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from company_lens.evals.models import ReportingTarget
from company_lens.evals.orchestrator import EvaluationRequest, run_evaluation
from tests.evals.fakes_langfuse import FakeLangfuse
from tests.evals.test_evaluation_orchestrator import PassingAgent, _agent_provider, _settings

CONTRACTS = Path("specs/003-langfuse-evaluation-foundation/contracts")


def test_generated_execution_and_journal_validate_against_public_contracts(
    tmp_path: Path,
) -> None:
    client = FakeLangfuse()
    outcome = run_evaluation(
        EvaluationRequest(
            dataset_paths=(Path("evals/datasets/golden/core.v1.yaml"),),
            gate_path=Path("evals/gates/eval-fast.v1.yaml"),
            score_contract_path=Path("evals/score-contracts/foundation.v1.yaml"),
            output_dir=tmp_path,
            max_cases=1,
            commit_sha="abcdef1",
            reporting_target=ReportingTarget(repository="owner/repo", pr_number=1),
        ),
        settings=_settings(),
        client=client,
        agent_provider=_agent_provider(PassingAgent(client)),
    )
    execution_schema = _json("evaluation-execution.schema.json")
    journal_schema = _json("evaluation-journal.schema.json")
    registry = Registry().with_resource(
        execution_schema["$id"], Resource.from_contents(execution_schema)
    )

    Draft202012Validator(
        execution_schema,
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(json.loads((tmp_path / "evaluation-execution.json").read_text()))
    Draft202012Validator(
        journal_schema,
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(outcome.journal.model_dump(mode="json"))


def test_repository_score_contract_validates_against_schema() -> None:
    score_schema = _json("score-contract.schema.json")
    payload = yaml.safe_load(Path("evals/score-contracts/foundation.v1.yaml").read_text())

    Draft202012Validator(score_schema).validate(payload)


def _json(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
