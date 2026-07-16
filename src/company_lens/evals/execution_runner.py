from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Literal

from company_lens.agent.schemas import ExecutionPolicy
from company_lens.evals.agent_runner import run_golden_agent_observations
from company_lens.evals.execution_artifacts import materialize_execution_artifacts
from company_lens.evals.gates import EvaluationGate
from company_lens.evals.golden import GoldenDataset, GoldenDatasetCase
from company_lens.evals.journal import checkpoint_evaluation_journal
from company_lens.evals.langfuse_experiment import run_dataset_experiment
from company_lens.evals.langfuse_scores import ReconciledScoreConfigs
from company_lens.evals.manifest import DatasetSnapshot, EvaluationRunManifest
from company_lens.evals.models import (
    CaseIdentity,
    EvaluationExecution,
    EvaluationRecoveryJournal,
)
from company_lens.evals.score_contract import ScoreContract


def execute_preflighted_evaluation(
    *,
    execution_id: str,
    commit_sha: str,
    output_dir: Path,
    journal_path: Path,
    journal: EvaluationRecoveryJournal,
    manifest: EvaluationRunManifest,
    datasets: tuple[GoldenDataset, ...],
    selected: dict[str, tuple[GoldenDatasetCase, ...]],
    snapshots: dict[str, DatasetSnapshot],
    gate: EvaluationGate,
    score_contract: ScoreContract,
    score_configs: ReconciledScoreConfigs,
    client: Any,
    agent_provider: Callable[[], AbstractContextManager[Any]],
    session_prefix: str,
    max_concurrency: int,
    max_tool_calls: int,
    max_retries_per_node: int,
    max_repair_attempts: int,
    reporting_requested: bool,
) -> tuple[Literal[0, 1, 2], EvaluationExecution, EvaluationRecoveryJournal]:
    journal = checkpoint_evaluation_journal(
        journal_path,
        journal,
        phase="preflighted",
        manifest=manifest,
    )
    journal = checkpoint_evaluation_journal(journal_path, journal, phase="running")
    policy = ExecutionPolicy(
        max_tool_calls=max_tool_calls,
        max_retries_per_node=max_retries_per_node,
        max_repair_attempts=max_repair_attempts,
    )
    try:
        with agent_provider() as agent:
            for dataset in datasets:
                cases = selected[dataset.name]

                def execute_case(
                    case: GoldenDatasetCase,
                    selected_dataset: GoldenDataset = dataset,
                ) -> Any:
                    single = selected_dataset.model_copy(update={"cases": (case,)})
                    return run_golden_agent_observations(
                        single,
                        agent,
                        policy=policy,
                        case_ids=(case.id,),
                        session_prefix=session_prefix,
                        run_token=execution_id,
                    )[0]

                run = run_dataset_experiment(
                    client,
                    client.get_dataset(
                        dataset.name,
                        version=snapshots[dataset.name].version_timestamp,
                    ),
                    dataset,
                    cases,
                    snapshot=snapshots[dataset.name],
                    execution_id=execution_id,
                    commit_sha=commit_sha,
                    manifest_fingerprint=manifest.manifest_fingerprint,
                    score_contract=score_contract,
                    score_bindings=score_configs,
                    execute_case=execute_case,
                    gate=gate,
                    max_concurrency=max_concurrency,
                )
                terminal_cases = (
                    *journal.terminal_cases,
                    *(
                        CaseIdentity(dataset_name=dataset.name, case_id=result.case_id)
                        for result in run.case_results
                    ),
                )
                journal = checkpoint_evaluation_journal(
                    journal_path,
                    journal,
                    dataset_runs=(*journal.dataset_runs, run),
                    terminal_cases=terminal_cases,
                )
    except Exception:
        final = checkpoint_evaluation_journal(
            journal_path,
            journal,
            phase="reporting" if reporting_requested else "terminal",
            status="partial" if journal.dataset_runs else "errored",
            gate_status="not_evaluated",
            failure_codes=tuple(
                dict.fromkeys((*journal.failure_codes, "evaluation_execution_failed"))
            ),
        )
        return 2, materialize_execution_artifacts(final, output_dir), final

    if any(run.status != "completed" for run in journal.dataset_runs):
        status: Literal["completed", "partial"] = "partial"
        gate_status: Literal["passed", "failed", "not_evaluated"] = "not_evaluated"
        exit_code: Literal[0, 1, 2] = 2
    elif any(run.gate_status == "failed" for run in journal.dataset_runs):
        status, gate_status, exit_code = "completed", "failed", 1
    else:
        status, gate_status, exit_code = "completed", "passed", 0
    final = checkpoint_evaluation_journal(
        journal_path,
        journal,
        phase="reporting" if reporting_requested else "terminal",
        status=status,
        gate_status=gate_status,
    )
    return exit_code, materialize_execution_artifacts(final, output_dir), final
