from __future__ import annotations

import uuid

from company_lens.agent.schemas import (
    AgentRunStatus,
    AgentState,
    AnswerValidation,
    ExecutionPolicy,
)
from company_lens.evals.golden import GoldenDatasetCase
from company_lens.evals.observation import case_observation_from_state


def test_projection_keeps_only_privacy_safe_citation_signals() -> None:
    case = _case(citation_mode="required")
    state = _state(
        final_answer="Sensitive answer text [evidence-1]",
        answer_validation=AnswerValidation(
            valid=False,
            claims=(),
            cited_evidence_ids=("evidence-1",),
            unknown_evidence_ids=("unknown-2", "unknown-1"),
            reason_codes=("unknown_evidence", "missing_claim_citation", "unknown_evidence"),
        ),
    )

    observation = case_observation_from_state(case, state)

    assert observation.outcome == "observed"
    assert observation.citation.answer_present is True
    assert observation.citation.valid is False
    assert observation.citation.unknown_evidence_ids == ("unknown-1", "unknown-2")
    assert observation.citation.reason_codes == (
        "missing_claim_citation",
        "unknown_evidence",
    )
    assert "Sensitive answer" not in observation.model_dump_json()


def test_missing_answer_is_observed_behavior_failure() -> None:
    observation = case_observation_from_state(_case(citation_mode="required"), _state())

    assert observation.outcome == "observed"
    assert observation.failure_code is None
    assert observation.citation.valid is False
    assert observation.citation.reason_codes == ("missing_answer",)


def test_missing_required_validation_is_infrastructure_error() -> None:
    observation = case_observation_from_state(
        _case(citation_mode="required"),
        _state(final_answer="Answer without validator output"),
    )

    assert observation.outcome == "infrastructure_error"
    assert observation.failure_code == "citation_validation_unavailable"
    assert observation.citation.valid is None


def test_not_applicable_case_has_no_citation_verdict() -> None:
    observation = case_observation_from_state(
        _case(citation_mode="not_applicable"),
        _state(final_answer="No source-derived claim"),
    )

    assert observation.outcome == "observed"
    assert observation.citation.mode == "not_applicable"
    assert observation.citation.valid is None
    assert observation.citation.reason_codes == ()


def _state(**updates: object) -> AgentState:
    state: AgentState = {  # type: ignore[typeddict-item]
        "run_id": uuid.uuid4(),
        "session_id": "evaluation-session",
        "question": "Question",
        "policy": ExecutionPolicy(),
        "status": AgentRunStatus.COMPLETED,
    }
    state.update(updates)  # type: ignore[typeddict-item]
    return state


def _case(*, citation_mode: str) -> GoldenDatasetCase:
    return GoldenDatasetCase.model_validate(
        {
            "id": "structured_example_revenue_001",
            "category": "structured_financial",
            "conversation": [{"role": "user", "content": "What was revenue?"}],
            "citation_mode": citation_mode,
            "expected": {
                "companies": [
                    {
                        "mention": "Example",
                        "status": "unresolved",
                        "source": "current_question",
                    }
                ],
                "metrics": [],
                "route": {"expected_route": "unsupported"},
            },
        }
    )
