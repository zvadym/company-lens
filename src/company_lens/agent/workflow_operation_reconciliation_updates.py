from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *
from company_lens.agent.workflow_errors import _event

_NODE = "reconcile_operations"


def _provider_failure_update(
    error: AgentError,
    started: float,
    reason_codes: tuple[str, ...],
    attempts: int,
) -> dict[str, object]:
    return {
        "status": AgentRunStatus.FAILED,
        "errors": (error,),
        "node_attempts": (NodeAttempt(node=_NODE, attempts=attempts),),
        "trajectory": (
            _event(
                _NODE,
                TrajectoryStatus.FAILED,
                "Operation reconciliation failed at the model boundary.",
                started,
                details=_trajectory_details(
                    reason_codes,
                    attempts=attempts,
                    outcome="provider_failure",
                ),
            ),
        ),
    }


def _semantic_failure_update(
    error: AgentError,
    started: float,
    reason_codes: tuple[str, ...],
    *,
    attempts: int,
) -> dict[str, object]:
    update: dict[str, object] = {
        "status": AgentRunStatus.FAILED,
        "errors": (error,),
        "trajectory": (
            _event(
                _NODE,
                TrajectoryStatus.FAILED,
                "Operation reconciliation failed plan validation.",
                started,
                details=_trajectory_details(
                    reason_codes,
                    attempts=attempts,
                    outcome="semantic_failure",
                ),
            ),
        ),
    }
    if attempts > 0:
        update["node_attempts"] = (NodeAttempt(node=_NODE, attempts=attempts),)
    return update


def _trajectory_details(
    reason_codes: tuple[str, ...],
    *,
    attempts: int,
    outcome: str,
    decision_count: int = 0,
) -> dict[str, str | int | float | bool | None]:
    return {
        "required": True,
        "conflict_reasons": ",".join(reason_codes),
        "conflict_count": len(reason_codes),
        "decision_count": decision_count,
        "attempts": attempts,
        "outcome": outcome,
    }


__all__ = (
    "_provider_failure_update",
    "_semantic_failure_update",
    "_trajectory_details",
)
