from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _normalized_analysis_question(
    state: AgentState,
    analysis: QuestionAnalysis | None,
) -> str:
    return analysis.normalized_question if analysis is not None else state["question"]


def _resolve_entities(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("resolve_entities")
    started = time.monotonic()
    try:
        analysis = state.get("analysis")
        resolved = _resolve_question_entities(
            state["question"],
            analysis,
            runtime.context.tools,
        )
        resolved, extraction_attempts, extraction_error = _resolve_extracted_company_mentions(
            state,
            runtime,
            resolved,
            analysis,
        )
    except ResearchToolError as exc:
        error = exc.error.model_copy(update={"node": "resolve_entities"})
        return {
            "status": AgentRunStatus.FAILED,
            "errors": (error,),
            "node_attempts": (NodeAttempt(node="resolve_entities", attempts=1),),
            "trajectory": (_failed_event("resolve_entities", started),),
        }
    except Exception:
        error = _agent_error(
            "resolve_entities",
            "entity_resolution_failed",
            "Entity resolution failed.",
            severity=AgentErrorSeverity.TERMINAL,
        )
        return {
            "status": AgentRunStatus.FAILED,
            "errors": (error,),
            "node_attempts": (NodeAttempt(node="resolve_entities", attempts=1),),
            "trajectory": (_failed_event("resolve_entities", started),),
        }
    update: dict[str, object] = {
        "current_resolved_query": resolved,
        "resolved_query": resolved,
        "node_attempts": (
            NodeAttempt(node="resolve_entities", attempts=max(1, extraction_attempts)),
        ),
        "trajectory": (
            _event(
                "resolve_entities",
                TrajectoryStatus.COMPLETED,
                (
                    "Entity resolution completed with a provider fallback."
                    if extraction_error is not None
                    else "Entity resolution completed."
                ),
                started,
                details={
                    "entities": len(resolved.entities),
                    "company_extraction_attempts": extraction_attempts,
                },
            ),
        ),
    }
    if extraction_error is not None:
        update["errors"] = (extraction_error,)
    return update


__all__ = ("_normalized_analysis_question", "_resolve_entities")
