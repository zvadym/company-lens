from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from dataclasses import dataclass

from company_lens.agent.workflow_context import *


@dataclass(frozen=True)
class ResearchAgentRuntime:
    model_provider: ResearchModelProvider
    tools: ResearchTools
    max_session_messages: int = 20
    max_cached_source_results: int = 20
    retrieval_index_name: str = "default"
    retrieval_index_version: str = DEFAULT_OPENAI_INDEX_VERSION
    semantic_support_judge: SemanticSupportJudge | None = None
    source_checker: SourceChecker | None = None


class ResearchAgent:
    def __init__(
        self,
        *,
        runtime: ResearchAgentRuntime,
        graph: CompiledStateGraph[AgentState, ResearchAgentRuntime, AgentState, AgentState]
        | None = None,
    ) -> None:
        self._runtime = runtime
        self._graph = graph or build_research_graph()

    def run(
        self,
        question: str,
        *,
        session_id: str,
        policy: ExecutionPolicy | None = None,
        run_id: uuid.UUID | None = None,
    ) -> AgentState:
        state = create_initial_agent_state(
            question,
            session_id=session_id,
            policy=policy,
            run_id=run_id,
        )
        recursion_limit = 24 + state["policy"].max_repair_attempts * 2
        result = self._graph.invoke(
            state,
            config={"recursion_limit": recursion_limit},
            context=self._runtime,
        )
        return cast(AgentState, result)


def create_initial_agent_state(
    question: str,
    *,
    session_id: str,
    policy: ExecutionPolicy | None = None,
    run_id: uuid.UUID | None = None,
) -> AgentState:
    cleaned = " ".join(question.split())
    if not cleaned:
        raise ValueError("Research question cannot be blank.")
    if not session_id.strip():
        raise ValueError("session_id cannot be blank.")
    now = datetime.now(UTC)
    return {
        "run_id": run_id or uuid.uuid4(),
        "session_id": session_id,
        "question": cleaned,
        "policy": policy or ExecutionPolicy(),
        "status": AgentRunStatus.RUNNING,
        "messages": (SessionMessage(role="user", content=cleaned, created_at=now),),
        "session_memory": SessionMemory(),
        "retrieval_results": (),
        "financial_results": (),
        "macro_results": (),
        "calculations": (),
        "branch_outcomes": (),
        "evidence": (),
        "chart_spec": None,
        "draft_answer": None,
        "final_answer": None,
        "claims": (),
        "citations": (),
        "source_previews": (),
        "errors": (),
        "trajectory": (),
        "node_attempts": (),
        "tool_calls_used": 0,
        "repair_attempts": 0,
    }


def build_research_graph(
    checkpointer: BaseCheckpointSaver[str] | None = None,
    *,
    interrupt_before: list[str] | None = None,
) -> CompiledStateGraph[AgentState, ResearchAgentRuntime, AgentState, AgentState]:
    builder = StateGraph(
        AgentState,
        context_schema=ResearchAgentRuntime,
        input_schema=AgentState,
        output_schema=AgentState,
    )
    builder.add_node("start_turn", _observed_node("start_turn", _start_turn))
    builder.add_node("parse_question", _observed_node("parse_question", _parse_question))
    builder.add_node(
        "answer_session_context",
        _observed_node("answer_session_context", _answer_session_context),
    )
    builder.add_node("resolve_entities", _observed_node("resolve_entities", _resolve_entities))
    builder.add_node(
        "prepare_company_data",
        _observed_node("prepare_company_data", _prepare_company_data),
    )
    builder.add_node("plan_request", _observed_node("plan_request", _plan_request))
    builder.add_node(
        "hydrate_cached_results",
        _observed_node("hydrate_cached_results", _hydrate_cached_results),
    )
    builder.add_node(
        "retrieve_documents", _observed_node("retrieve_documents", _retrieve_documents)
    )
    builder.add_node(
        "query_financial_facts",
        _observed_node("query_financial_facts", _query_financial_facts),
    )
    builder.add_node(
        "query_macro_series", _observed_node("query_macro_series", _query_macro_series)
    )
    builder.add_node("evaluate_context", _observed_node("evaluate_context", _evaluate_context))
    builder.add_node("calculate_metrics", _observed_node("calculate_metrics", _calculate_metrics))
    builder.add_node(
        "generate_chart_spec", _observed_node("generate_chart_spec", _generate_chart_spec)
    )
    builder.add_node("merge_evidence", _observed_node("merge_evidence", _merge_evidence))
    builder.add_node("generate_answer", _observed_node("generate_answer", _generate_answer))
    builder.add_node(
        "validate_citations", _observed_node("validate_citations", _validate_citations)
    )
    builder.add_node("repair_or_abstain", _observed_node("repair_or_abstain", _repair_or_abstain))
    builder.add_node("finalize_response", _observed_node("finalize_response", _finalize_response))

    builder.add_edge(START, "start_turn")
    builder.add_edge("start_turn", "parse_question")
    builder.add_edge("parse_question", "answer_session_context")
    builder.add_conditional_edges(
        "answer_session_context",
        _route_after_session_context,
        ["resolve_entities", END],
    )
    builder.add_edge("resolve_entities", "prepare_company_data")
    builder.add_edge("prepare_company_data", "plan_request")
    builder.add_edge("plan_request", "hydrate_cached_results")
    builder.add_conditional_edges(
        "hydrate_cached_results",
        _dispatch_source_branches,
        [
            "retrieve_documents",
            "query_financial_facts",
            "query_macro_series",
            "evaluate_context",
        ],
    )
    builder.add_edge("retrieve_documents", "evaluate_context")
    builder.add_edge("query_financial_facts", "evaluate_context")
    builder.add_edge("query_macro_series", "evaluate_context")
    builder.add_conditional_edges(
        "evaluate_context",
        _dispatch_calculation_branches,
        ["calculate_metrics", "generate_chart_spec", "finalize_response"],
    )
    builder.add_edge("calculate_metrics", "generate_chart_spec")
    builder.add_conditional_edges(
        "generate_chart_spec",
        _route_after_chart,
        ["merge_evidence", "finalize_response"],
    )
    builder.add_conditional_edges(
        "merge_evidence",
        _route_after_merge,
        ["generate_answer", "finalize_response"],
    )
    builder.add_conditional_edges(
        "generate_answer",
        _route_after_answer,
        ["validate_citations", "finalize_response"],
    )
    builder.add_conditional_edges(
        "validate_citations",
        _route_after_validation,
        ["finalize_response", "repair_or_abstain"],
    )
    builder.add_conditional_edges(
        "repair_or_abstain",
        _route_after_repair,
        ["validate_citations", "finalize_response"],
    )
    builder.add_edge("finalize_response", END)
    return builder.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)


def _observed_node[**P, R](name: str, function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        state = args[0] if args and isinstance(args[0], dict) else None
        run_id = state.get("run_id") if state is not None else None
        session_id = state.get("session_id") if state is not None else None
        with (
            bind_context(run_id=run_id, session_id=session_id),
            observe_operation(
                f"agent.node.{name}",
                kind="agent_node",
                attributes={"company_lens.node.name": name},
            ),
        ):
            return function(*args, **kwargs)

    return wrapped


__all__ = (
    "ResearchAgentRuntime",
    "ResearchAgent",
    "create_initial_agent_state",
    "build_research_graph",
    "_observed_node",
)  # noqa: E501
