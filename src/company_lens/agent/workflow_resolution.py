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
        memory = state.get("session_memory")
        resolved = _resolve_extracted_company_mentions(
            state,
            runtime,
            resolved,
            analysis,
        )
        resolved = _merge_follow_up_if_needed(resolved, analysis, memory)
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
    frame = _build_research_frame(
        question=state["question"],
        analysis=state.get("analysis"),
        resolved=resolved,
        memory=state.get("session_memory"),
    )
    return {
        "resolved_query": resolved,
        "research_frame": frame,
        "node_attempts": (NodeAttempt(node="resolve_entities", attempts=1),),
        "trajectory": (
            _event(
                "resolve_entities",
                TrajectoryStatus.COMPLETED,
                "Entity resolution completed.",
                started,
                details={"entities": len(resolved.entities)},
            ),
        ),
    }

__all__ = ('_normalized_analysis_question', '_resolve_entities')
