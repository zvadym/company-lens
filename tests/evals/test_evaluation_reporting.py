from __future__ import annotations

from pathlib import Path

from company_lens.evals.models import ReportingTarget
from company_lens.evals.orchestrator import EvaluationRequest, run_evaluation
from tests.evals.fakes_langfuse import FakeLangfuse
from tests.evals.test_evaluation_orchestrator import PassingAgent, _agent_provider, _settings


def test_public_evaluation_artifacts_exclude_forbidden_content(tmp_path: Path) -> None:
    client = FakeLangfuse()
    run_evaluation(
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
    combined = "\n".join(
        (tmp_path / name).read_text(encoding="utf-8").lower()
        for name in (
            "evaluation-execution.json",
            "evaluation-journal.json",
            "evaluation-summary.md",
        )
    )

    for forbidden in (
        "revenue was reported",
        "raw_prompt",
        "final_answer",
        "provider_payload",
        "evidence_passage",
        "stack_trace",
        "secret provider payload",
    ):
        assert forbidden not in combined
