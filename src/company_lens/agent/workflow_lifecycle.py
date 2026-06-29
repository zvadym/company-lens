from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _start_turn(state: AgentState, runtime: Runtime[ResearchAgentRuntime]) -> dict[str, object]:
    started = time.monotonic()
    retained = max(1, runtime.context.max_session_messages - 1)
    messages = tuple(state.get("messages", ())[-retained:])
    return {
        "status": AgentRunStatus.RUNNING,
        "messages": Overwrite(messages),
        "analysis": None,
        "resolved_query": None,
        "execution_plan": None,
        "retrieval_results": Overwrite(()),
        "financial_results": Overwrite(()),
        "macro_results": Overwrite(()),
        "calculations": Overwrite(()),
        "branch_outcomes": Overwrite(()),
        "evidence": (),
        "chart_spec": None,
        "draft_answer": None,
        "final_answer": None,
        "answer_validation": None,
        "repair_attempts": 0,
        "citations": (),
        "errors": Overwrite(()),
        "trajectory": Overwrite(
            (
                _event(
                    "start_turn",
                    TrajectoryStatus.COMPLETED,
                    "Research turn initialized.",
                    started,
                ),
            )
        ),
        "node_attempts": Overwrite(()),
        "tool_calls_used": Overwrite(0),
    }


def _parse_question(state: AgentState, runtime: Runtime[ResearchAgentRuntime]) -> dict[str, object]:
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("parse_question")
    started = time.monotonic()
    messages = (
        ModelMessage(
            role="system",
            content=(
                "Classify a public-company research question using these exact route semantics: "
                "rag_only means company documents only; structured_only means company financial "
                "facts only; api_only means cached macro series without derived arithmetic; "
                "calculation means any requested change, growth, margin, index, average, or "
                "correlation over financial or macro observations; hybrid means two or more "
                "source kinds; unsupported means none of the available sources can answer. "
                "A request asking how a macro rate changed requires macro_series and calculations, "
                "not financial_facts. Add chart only when explicitly requested. Return short "
                "lowercase_snake_case reason codes, never reasoning. Use English for all "
                "structured fields, internal planning labels, reason codes, and tool-oriented "
                "summaries."
            ),
        ),
        *tuple(
            ModelMessage(role=message.role, content=message.content)
            for message in state["messages"]
        ),
    )
    output, attempts, error = _generate_structured_with_retries(
        runtime.context.model_provider,
        messages,
        QuestionAnalysis,
        purpose=ModelPurpose.PARSE,
        max_retries=state["policy"].max_retries_per_node,
        node="parse_question",
    )
    update = _model_node_update("parse_question", attempts, started, error)
    if error is not None:
        fallback_analysis = _fallback_follow_up_analysis(
            state["question"],
            state.get("session_memory"),
        )
        if fallback_analysis is not None:
            update.pop("errors", None)
            update["analysis"] = fallback_analysis
            update["trajectory"] = (
                *cast(tuple[TrajectoryEvent, ...], update["trajectory"]),
                _event(
                    "parse_question",
                    TrajectoryStatus.COMPLETED,
                    "Recovered classification from deterministic follow-up context.",
                    started,
                    details={"attempts": attempts},
                ),
            )
            return update
        update["status"] = _terminal_parse_status(error)
        if update["status"] is AgentRunStatus.ABSTAINED:
            update["draft_answer"] = _parse_failure_answer(state, error)
    elif output is not None:
        update["analysis"] = output
    return update

__all__ = ('_start_turn', '_parse_question')
