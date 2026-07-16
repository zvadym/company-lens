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
        "current_resolved_query": None,
        "resolved_query": None,
        "research_frame": None,
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
        _system_prompt_message(runtime, "agent/parse-question"),
        *tuple(
            ModelMessage(role=message.role, content=message.content)
            for message in state["messages"]
        ),
    )
    output, attempts, error = _generate_structured_with_retries(
        runtime.context.model_provider,
        messages,
        ModelQuestionAnalysis,
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
        update["analysis"] = _domain_question_analysis(output)
    return update


def _domain_question_analysis(output: ModelQuestionAnalysis) -> QuestionAnalysis:
    capabilities = output.required_capabilities
    chart_requested = output.chart_requested
    calculation_intents = tuple(
        domain_calculation_intent(intent) for intent in output.calculation_intents
    )
    inherit_previous_calculation_intents = output.inherit_previous_calculation_intents
    reason_codes = output.reason_codes
    route = output.route
    if output.route is ResearchRoute.UNSUPPORTED:
        if capabilities or chart_requested or calculation_intents:
            reason_codes = tuple(dict.fromkeys((*reason_codes, "unsupported_analysis_normalized")))
        capabilities = ()
        chart_requested = False
        calculation_intents = ()
        inherit_previous_calculation_intents = False
    elif _growth_calculation_capability_needed(output):
        capabilities = tuple(dict.fromkeys((*capabilities, AgentCapability.CALCULATIONS)))
        reason_codes = tuple(dict.fromkeys((*reason_codes, "calculation_capability_inferred")))
        if route in {ResearchRoute.STRUCTURED_ONLY, ResearchRoute.API_ONLY}:
            route = ResearchRoute.CALCULATION
    return QuestionAnalysis(
        normalized_question=output.normalized_question,
        route=route,
        required_capabilities=capabilities,
        chart_requested=chart_requested,
        is_follow_up=output.is_follow_up,
        calculation_intents=calculation_intents,
        inherit_previous_calculation_intents=inherit_previous_calculation_intents,
        reason_codes=reason_codes,
    )


def _growth_calculation_capability_needed(output: ModelQuestionAnalysis) -> bool:
    capabilities = set(output.required_capabilities)
    if AgentCapability.CALCULATIONS in capabilities:
        return False
    if not capabilities.intersection(
        {AgentCapability.FINANCIAL_FACTS, AgentCapability.MACRO_SERIES}
    ):
        return False
    return bool(output.calculation_intents)


__all__ = (
    "_start_turn",
    "_parse_question",
    "_domain_question_analysis",
    "_growth_calculation_capability_needed",
)
