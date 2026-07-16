from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from company_lens.evals.models import EvaluationRecoveryJournal


class EvaluationJournalError(RuntimeError):
    pass


def load_evaluation_journal(path: Path) -> EvaluationRecoveryJournal:
    try:
        return EvaluationRecoveryJournal.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvaluationJournalError("evaluation_journal_invalid") from exc


def initialize_evaluation_journal(
    path: Path,
    journal: EvaluationRecoveryJournal,
) -> None:
    if journal.sequence != 0:
        raise EvaluationJournalError("initial_journal_sequence_invalid")
    if path.exists():
        raise EvaluationJournalError("evaluation_journal_already_exists")
    _atomic_write(path, journal.model_dump_json(indent=2) + "\n")


def checkpoint_evaluation_journal(
    path: Path,
    previous: EvaluationRecoveryJournal,
    **updates: Any,
) -> EvaluationRecoveryJournal:
    current = load_evaluation_journal(path)
    if current != previous:
        raise EvaluationJournalError("evaluation_journal_concurrent_update")
    updated_at = datetime.now(UTC)
    if updated_at <= previous.updated_at:
        updated_at = previous.updated_at + timedelta(microseconds=1)
    candidate = EvaluationRecoveryJournal.model_validate(
        {
            **previous.model_dump(),
            **updates,
            "sequence": previous.sequence + 1,
            "updated_at": updated_at,
        }
    )
    _validate_monotonic(previous, candidate)
    _atomic_write(path, candidate.model_dump_json(indent=2) + "\n")
    return candidate


def _validate_monotonic(
    previous: EvaluationRecoveryJournal,
    candidate: EvaluationRecoveryJournal,
) -> None:
    if candidate.execution_id != previous.execution_id:
        raise EvaluationJournalError("evaluation_execution_identity_changed")
    if candidate.sequence != previous.sequence + 1:
        raise EvaluationJournalError("evaluation_journal_sequence_invalid")
    previous_cases = set(previous.terminal_cases)
    if not previous_cases.issubset(set(candidate.terminal_cases)):
        raise EvaluationJournalError("terminal_case_removed")
    old_runs = {run.dataset_name: run for run in previous.dataset_runs}
    new_runs = {run.dataset_name: run for run in candidate.dataset_runs}
    if not set(old_runs).issubset(new_runs):
        raise EvaluationJournalError("dataset_run_removed")
    for name, old_run in old_runs.items():
        if old_run.selected_case_ids != new_runs[name].selected_case_ids:
            raise EvaluationJournalError("dataset_run_identity_changed")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


atomic_write = _atomic_write
