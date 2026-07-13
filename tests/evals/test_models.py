from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from company_lens.evals.models import CaseIdentity, EvaluationRecoveryJournal


def test_initialized_journal_accepts_dataset_scoped_case_identity() -> None:
    journal = EvaluationRecoveryJournal(
        execution_id=uuid4(),
        sequence=0,
        updated_at=datetime.now(UTC),
        phase="initialized",
        status="running",
        gate_status="pending",
        reporting_status="not_requested",
        terminal_cases=(CaseIdentity(dataset_name="core", case_id="case_001"),),
    )

    assert journal.terminal_cases[0].dataset_name == "core"


def test_journal_rejects_terminal_running_state() -> None:
    with pytest.raises(
        ValidationError,
        match="terminal phase requires a terminal evaluation status",
    ):
        EvaluationRecoveryJournal(
            execution_id=uuid4(),
            sequence=1,
            updated_at=datetime.now(UTC),
            phase="terminal",
            status="running",
            gate_status="pending",
            reporting_status="not_requested",
        )


def test_journal_requires_target_for_pending_reporting() -> None:
    with pytest.raises(ValidationError, match="reporting target"):
        EvaluationRecoveryJournal(
            execution_id=uuid4(),
            sequence=0,
            updated_at=datetime.now(UTC),
            phase="initialized",
            status="running",
            gate_status="pending",
            reporting_status="pending",
        )
