from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from company_lens.config import Settings
from company_lens.evals.orchestrator import EvaluationRequest, run_evaluation
from tests.evals.fakes_langfuse import FakeLangfuse


class SdkError(Exception):
    pass


class ScoreConfigFailureClient(FakeLangfuse):
    def create_score_config(self, *, name: str, data_type: str, **kwargs: Any) -> Any:
        raise SdkError("invalid request")


class NeverCalledAgent:
    def run(self, *_: Any, **__: Any) -> Any:
        raise AssertionError("agent must not run after a failed preflight")


def test_score_config_sdk_failure_materializes_terminal_artifacts(tmp_path: Path) -> None:
    outcome = run_evaluation(
        EvaluationRequest(
            dataset_paths=(Path("evals/datasets/golden/core.v1.yaml"),),
            gate_path=Path("evals/gates/eval-fast.v1.yaml"),
            score_contract_path=Path("evals/score-contracts/foundation.v1.yaml"),
            output_dir=tmp_path,
            max_cases=1,
            commit_sha="abcdef1",
        ),
        settings=Settings(langfuse_project_id="project-testing", _env_file=None),
        client=ScoreConfigFailureClient(),
        agent_provider=_agent_provider(),
    )

    assert outcome.exit_code == 2
    assert outcome.execution.status == "errored"
    assert outcome.execution.gate_status == "not_evaluated"
    assert outcome.execution.failure_codes == ("evaluation_preflight_failed",)
    assert outcome.journal.phase == "terminal"
    assert (tmp_path / "evaluation-execution.json").exists()
    assert (tmp_path / "evaluation-summary.md").exists()


@contextmanager
def _agent_provider() -> Iterator[NeverCalledAgent]:
    yield NeverCalledAgent()
