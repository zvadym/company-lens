from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Overwrite, Send
from pydantic import BaseModel

from company_lens.agent.model import (
    ModelMessage,
    ModelProviderError,
    ModelPurpose,
    ResearchModelProvider,
)
from company_lens.agent.schemas import (
    AgentCapability,
    AgentError,
    AgentErrorCategory,
    AgentErrorSeverity,
    AgentRunStatus,
    AgentState,
    BranchOutcome,
    BranchStatus,
    CachedSourceResult,
    CalculationBranch,
    CalculationBranchResult,
    ChartBranch,
    CitationReference,
    DocumentRetrievalBranch,
    EvidenceEnvelope,
    EvidenceKind,
    ExecutionBranch,
    ExecutionPlan,
    ExecutionPolicy,
    FinancialBranchResult,
    FinancialFactsBranch,
    MacroBranchResult,
    MacroSeriesBranch,
    ModelExecutionBranch,
    ModelExecutionPlan,
    NodeAttempt,
    QuestionAnalysis,
    ResearchRoute,
    RetrievalBranchResult,
    SessionMemory,
    SessionMessage,
    TrajectoryEvent,
    TrajectoryStatus,
)
from company_lens.agent.tools import ResearchToolError, ResearchTools
from company_lens.analytics.calculations import (
    absolute_change,
    compound_annual_growth_rate,
    correlation,
    margin,
    normalised_index,
    percentage_change,
    quarter_over_quarter_growth,
    rolling_average,
    year_over_year_growth,
)
from company_lens.analytics.charts import generate_chart_specification
from company_lens.analytics.schemas import (
    CalculationResult,
    ChartPoint,
    ChartSeries,
    NumericObservation,
    ValidatedChartDataset,
)
from company_lens.evidence.claims import extract_claims
from company_lens.evidence.registry import EvidenceRegistry, SourceChecker
from company_lens.evidence.schemas import EvidenceMetadata, SemanticSupportStatus
from company_lens.evidence.validation import AnswerValidator, SemanticSupportJudge
from company_lens.financials.schemas import FinancialFactObservation
from company_lens.retrieval.adaptive_schemas import ResolvedQuery
from company_lens.retrieval.embeddings import DEFAULT_OPENAI_INDEX_VERSION

SOURCE_KINDS = {"retrieve_documents", "query_financial_facts", "query_macro_series"}


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
    builder.add_node("start_turn", _start_turn)
    builder.add_node("parse_question", _parse_question)
    builder.add_node("resolve_entities", _resolve_entities)
    builder.add_node("plan_request", _plan_request)
    builder.add_node("hydrate_cached_results", _hydrate_cached_results)
    builder.add_node("retrieve_documents", _retrieve_documents)
    builder.add_node("query_financial_facts", _query_financial_facts)
    builder.add_node("query_macro_series", _query_macro_series)
    builder.add_node("evaluate_context", _evaluate_context)
    builder.add_node("calculate_metrics", _calculate_metrics)
    builder.add_node("generate_chart_spec", _generate_chart_spec)
    builder.add_node("merge_evidence", _merge_evidence)
    builder.add_node("generate_answer", _generate_answer)
    builder.add_node("validate_citations", _validate_citations)
    builder.add_node("repair_or_abstain", _repair_or_abstain)
    builder.add_node("finalize_response", _finalize_response)

    builder.add_edge(START, "start_turn")
    builder.add_edge("start_turn", "parse_question")
    builder.add_edge("parse_question", "resolve_entities")
    builder.add_edge("resolve_entities", "plan_request")
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
                "lowercase_snake_case reason codes, never reasoning."
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
        update["status"] = _terminal_model_status(error)
    elif output is not None:
        update["analysis"] = output
    return update


def _resolve_entities(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("resolve_entities")
    started = time.monotonic()
    try:
        resolved = runtime.context.tools.resolve_entities(state["question"])
        analysis = state.get("analysis")
        memory = state.get("session_memory")
        if (
            analysis is not None
            and analysis.is_follow_up
            and memory is not None
            and memory.last_resolved_query is not None
        ):
            resolved = _merge_follow_up_resolution(resolved, memory.last_resolved_query)
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
    return {
        "resolved_query": resolved,
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


def _plan_request(state: AgentState, runtime: Runtime[ResearchAgentRuntime]) -> dict[str, object]:
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("plan_request")
    analysis = state.get("analysis")
    resolved = state.get("resolved_query")
    if analysis is None or resolved is None:
        missing_error = _validation_error("plan_request", "missing_planning_inputs")
        return {"status": AgentRunStatus.FAILED, "errors": (missing_error,)}
    started = time.monotonic()
    memory = state.get("session_memory")
    previous_plan = memory.last_execution_plan if memory is not None else None
    planning_context = json.dumps(
        {
            "question": state["question"],
            "analysis": analysis.model_dump(mode="json"),
            "resolved_query": resolved.model_dump(mode="json"),
            "policy": state["policy"].model_dump(mode="json"),
            "previous_plan": (
                previous_plan.model_dump(mode="json") if previous_plan is not None else None
            ),
        },
        sort_keys=True,
    )
    messages = (
        ModelMessage(
            role="system",
            content=(
                "Create a minimal typed execution plan for CompanyLens. Use only resolved company "
                "IDs. Company metrics use query_financial_facts; economic rates and indicators "
                "use query_macro_series. A requested change or growth requires a calculation route "
                "with a source branch and calculate_metrics branch. Source branches must be "
                "independent. Calculations may depend on financial or macro branches; a chart may "
                "depend on one source or calculation branch. The plan route must describe its "
                "concrete branches. Mark a branch optional only when the question can still be "
                "answered without it. Do not include explanations beyond short reason codes."
            ),
        ),
        ModelMessage(role="user", content=planning_context),
    )
    output, attempts, error = _generate_structured_with_retries(
        runtime.context.model_provider,
        messages,
        ModelExecutionPlan,
        purpose=ModelPurpose.PLAN,
        max_retries=state["policy"].max_retries_per_node,
        node="plan_request",
    )
    update = _model_node_update("plan_request", attempts, started, error)
    if error is not None:
        update["status"] = _terminal_model_status(error)
        return update
    assert output is not None
    try:
        domain_plan = _canonicalize_plan_route(_domain_execution_plan(output))
        reconciled_analysis = _reconcile_analysis_with_plan(analysis, domain_plan)
        plan = _normalize_and_validate_plan(
            domain_plan,
            reconciled_analysis,
            resolved,
            state["policy"],
            retrieval_index_name=runtime.context.retrieval_index_name,
            retrieval_index_version=runtime.context.retrieval_index_version,
        )
    except ValueError:
        validation_error = _validation_error("plan_request", "invalid_execution_plan")
        update["errors"] = (validation_error,)
        update["status"] = AgentRunStatus.FAILED
        update["trajectory"] = (_failed_event("plan_request", started),)
        return update
    update["execution_plan"] = plan
    if reconciled_analysis != analysis:
        update["analysis"] = reconciled_analysis
    return update


def _hydrate_cached_results(state: AgentState) -> dict[str, object]:
    started = time.monotonic()
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("hydrate_cached_results")
    plan = state.get("execution_plan")
    memory = state.get("session_memory")
    if plan is None or memory is None:
        return _skipped("hydrate_cached_results")
    cache = {(item.kind, item.request_fingerprint): item for item in memory.cached_source_results}
    retrieval_results: list[RetrievalBranchResult] = []
    financial_results: list[FinancialBranchResult] = []
    macro_results: list[MacroBranchResult] = []
    outcomes: list[BranchOutcome] = []
    for branch in _source_branches(plan):
        cached = cache.get((branch.kind, _source_request_fingerprint(branch)))
        if cached is None:
            continue
        if isinstance(branch, DocumentRetrievalBranch) and cached.retrieval_result is not None:
            retrieval_results.append(
                RetrievalBranchResult(branch_id=branch.branch_id, result=cached.retrieval_result)
            )
        elif isinstance(branch, FinancialFactsBranch) and cached.financial_result is not None:
            financial_results.append(
                FinancialBranchResult(branch_id=branch.branch_id, result=cached.financial_result)
            )
        elif isinstance(branch, MacroSeriesBranch) and cached.macro_result is not None:
            macro_results.append(
                MacroBranchResult(branch_id=branch.branch_id, result=cached.macro_result)
            )
        else:
            continue
        outcomes.append(
            BranchOutcome(
                branch_id=branch.branch_id,
                kind=branch.kind,
                status=BranchStatus.COMPLETED,
                optional=branch.optional,
                attempts=0,
            )
        )
    return {
        "retrieval_results": tuple(retrieval_results),
        "financial_results": tuple(financial_results),
        "macro_results": tuple(macro_results),
        "branch_outcomes": tuple(outcomes),
        "trajectory": (
            _event(
                "hydrate_cached_results",
                TrajectoryStatus.COMPLETED,
                "Exact-match session results were hydrated.",
                started,
                details={"reused_results": len(outcomes)},
            ),
        ),
    }


def _dispatch_source_branches(state: AgentState) -> list[Send] | str:
    if state["status"] is not AgentRunStatus.RUNNING:
        return "evaluate_context"
    plan = state.get("execution_plan")
    if plan is None:
        return "evaluate_context"
    sends: list[Send] = []
    completed = {
        outcome.branch_id
        for outcome in state.get("branch_outcomes", ())
        if outcome.status is BranchStatus.COMPLETED
    }
    for branch in plan.branches:
        if branch.kind in SOURCE_KINDS and branch.branch_id not in completed:
            sends.append(Send(branch.kind, {**state, "active_branch": branch}))
    return sends or "evaluate_context"


def _retrieve_documents(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    branch = cast(DocumentRetrievalBranch, state["active_branch"])
    result, common = _run_source_tool(
        state,
        branch,
        runtime.context.tools.retrieve_documents,
        "retrieve_documents",
    )
    if result is not None:
        common["retrieval_results"] = (
            RetrievalBranchResult(branch_id=branch.branch_id, result=result),
        )
    return common


def _query_financial_facts(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    branch = cast(FinancialFactsBranch, state["active_branch"])
    result, common = _run_source_tool(
        state,
        branch,
        runtime.context.tools.query_financial_facts,
        "query_financial_facts",
    )
    if result is not None:
        common["financial_results"] = (
            FinancialBranchResult(branch_id=branch.branch_id, result=result),
        )
    return common


def _query_macro_series(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    branch = cast(MacroSeriesBranch, state["active_branch"])
    result, common = _run_source_tool(
        state,
        branch,
        runtime.context.tools.query_macro_series,
        "query_macro_series",
    )
    if result is not None:
        common["macro_results"] = (MacroBranchResult(branch_id=branch.branch_id, result=result),)
    return common


def _run_source_tool[RequestT, ResultT](
    state: AgentState,
    branch: DocumentRetrievalBranch | FinancialFactsBranch | MacroSeriesBranch,
    operation: Callable[[RequestT], ResultT],
    node: str,
) -> tuple[ResultT | None, dict[str, object]]:
    started = time.monotonic()
    max_attempts = _source_branch_max_attempts(state, branch.branch_id)
    result: ResultT | None = None
    error: AgentError | None = None
    attempts = 0
    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        try:
            result = operation(cast(RequestT, branch.request))
            error = None
            break
        except ResearchToolError as exc:
            error = exc.error.model_copy(update={"node": node, "attempt": attempt})
            if not error.recoverable:
                break
        except Exception:
            error = _agent_error(
                node,
                "tool_execution_failed",
                "A research data operation failed.",
                attempt=attempt,
                severity=AgentErrorSeverity.TERMINAL,
            )
            break
    status = BranchStatus.COMPLETED if result is not None else BranchStatus.FAILED
    outcome = BranchOutcome(
        branch_id=branch.branch_id,
        kind=branch.kind,
        status=status,
        optional=branch.optional,
        attempts=attempts,
        error=error,
    )
    update: dict[str, object] = {
        "branch_outcomes": (outcome,),
        "node_attempts": (NodeAttempt(node=f"{node}:{branch.branch_id}", attempts=attempts),),
        "tool_calls_used": attempts,
        "trajectory": (
            _event(
                node,
                TrajectoryStatus.COMPLETED if result is not None else TrajectoryStatus.FAILED,
                "Branch execution completed." if result is not None else "Branch execution failed.",
                started,
                details={"branch_id": branch.branch_id, "attempts": attempts},
            ),
        ),
    }
    if error is not None:
        update["errors"] = (error,)
    return result, update


def _evaluate_context(state: AgentState) -> dict[str, object]:
    started = time.monotonic()
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("evaluate_context")
    plan = state.get("execution_plan")
    if plan is None:
        error = _validation_error("evaluate_context", "missing_execution_plan")
        return {
            "status": AgentRunStatus.FAILED,
            "errors": (error,),
            "trajectory": (_failed_event("evaluate_context", started),),
        }
    if plan.route is ResearchRoute.UNSUPPORTED:
        error = _agent_error(
            "evaluate_context",
            "unsupported_question",
            "The question is outside the supported research capabilities.",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        return {
            "status": AgentRunStatus.ABSTAINED,
            "errors": (error,),
            "trajectory": (
                _event(
                    "evaluate_context",
                    TrajectoryStatus.COMPLETED,
                    "Unsupported question was explicitly abstained.",
                    started,
                ),
            ),
        }

    issues: list[tuple[ExecutionBranch, str]] = []
    outcomes = {item.branch_id: item for item in state.get("branch_outcomes", ())}
    for branch in _source_branches(plan):
        outcome = outcomes.get(branch.branch_id)
        if outcome is None or outcome.status is BranchStatus.FAILED:
            issues.append((branch, "execution_failed"))
        elif not _branch_has_evidence(state, branch):
            issues.append((branch, "insufficient_evidence"))

    required = [(branch, reason) for branch, reason in issues if not branch.optional]
    optional = [(branch, reason) for branch, reason in issues if branch.optional]
    errors = tuple(
        _agent_error(
            "evaluate_context",
            f"{reason}_{branch.branch_id}",
            "A research branch returned insufficient usable evidence."
            if reason == "insufficient_evidence"
            else "A required research branch failed.",
            category=AgentErrorCategory.TOOL,
            severity=AgentErrorSeverity.TERMINAL,
        )
        for branch, reason in issues
        if reason == "insufficient_evidence"
    )
    update: dict[str, object] = {
        "trajectory": (
            _event(
                "evaluate_context",
                TrajectoryStatus.COMPLETED,
                "Source branch context was evaluated.",
                started,
                details={"issues": len(issues)},
            ),
        ),
    }
    if errors:
        update["errors"] = errors
    if required:
        execution_failure = any(reason == "execution_failed" for _, reason in required)
        update["status"] = AgentRunStatus.FAILED if execution_failure else AgentRunStatus.ABSTAINED
    elif optional:
        if _has_any_source_evidence(state):
            update["status"] = AgentRunStatus.PARTIAL
        else:
            update["status"] = AgentRunStatus.ABSTAINED
    return update


def _dispatch_calculation_branches(state: AgentState) -> list[Send] | str:
    if state["status"] in {AgentRunStatus.FAILED, AgentRunStatus.ABSTAINED}:
        return "finalize_response"
    plan = state.get("execution_plan")
    if plan is None:
        return "finalize_response"
    branches = [branch for branch in plan.branches if isinstance(branch, CalculationBranch)]
    return [
        Send("calculate_metrics", {**state, "active_branch": branch}) for branch in branches
    ] or ("generate_chart_spec")


def _calculate_metrics(state: AgentState) -> dict[str, object]:
    branch = cast(CalculationBranch, state["active_branch"])
    started = time.monotonic()
    try:
        result = _execute_calculation(branch, state)
    except (ValueError, TypeError, ArithmeticError):
        error = _agent_error(
            "calculate_metrics",
            "calculation_invalid_inputs",
            "A deterministic calculation could not be completed from its typed inputs.",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        return {
            "branch_outcomes": (
                BranchOutcome(
                    branch_id=branch.branch_id,
                    kind=branch.kind,
                    status=BranchStatus.FAILED,
                    optional=branch.optional,
                    attempts=1,
                    error=error,
                ),
            ),
            "errors": (error,),
            "node_attempts": (
                NodeAttempt(node=f"calculate_metrics:{branch.branch_id}", attempts=1),
            ),
            "trajectory": (_failed_event("calculate_metrics", started),),
        }
    return {
        "calculations": (CalculationBranchResult(branch_id=branch.branch_id, result=result),),
        "branch_outcomes": (
            BranchOutcome(
                branch_id=branch.branch_id,
                kind=branch.kind,
                status=BranchStatus.COMPLETED,
                optional=branch.optional,
                attempts=1,
            ),
        ),
        "node_attempts": (NodeAttempt(node=f"calculate_metrics:{branch.branch_id}", attempts=1),),
        "trajectory": (
            _event(
                "calculate_metrics",
                TrajectoryStatus.COMPLETED,
                "Deterministic calculation completed.",
                started,
                details={"branch_id": branch.branch_id},
            ),
        ),
    }


def _generate_chart_spec(state: AgentState) -> dict[str, object]:
    started = time.monotonic()
    if state["status"] in {AgentRunStatus.FAILED, AgentRunStatus.ABSTAINED}:
        return _skipped("generate_chart_spec")
    plan = state.get("execution_plan")
    if plan is None:
        return {"status": AgentRunStatus.FAILED}

    calculation_issues = _failed_planned_branches(state, CalculationBranch)
    required_calculation_issues = [item for item in calculation_issues if not item.optional]
    if required_calculation_issues:
        return {
            "status": AgentRunStatus.FAILED,
            "trajectory": (_failed_event("generate_chart_spec", started),),
        }
    update: dict[str, object] = {}
    if calculation_issues:
        update["status"] = AgentRunStatus.PARTIAL

    chart = next((branch for branch in plan.branches if isinstance(branch, ChartBranch)), None)
    if chart is None:
        update["trajectory"] = (
            _event(
                "generate_chart_spec",
                TrajectoryStatus.SKIPPED,
                "No chart was requested.",
                started,
            ),
        )
        return update
    try:
        dataset = _chart_dataset(chart.dataset_ref, state)
        specification = generate_chart_specification(
            dataset,
            chart_type=chart.chart_type,
            title=chart.title,
            x_label=chart.x_label,
        )
    except (ValueError, TypeError):
        error = _agent_error(
            "generate_chart_spec",
            "invalid_chart_dataset",
            "The selected result cannot be represented as a validated chart dataset.",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        update.update(
            {
                "status": AgentRunStatus.PARTIAL if chart.optional else AgentRunStatus.FAILED,
                "errors": (error,),
                "trajectory": (_failed_event("generate_chart_spec", started),),
            }
        )
        return update
    update.update(
        {
            "chart_spec": specification,
            "trajectory": (
                _event(
                    "generate_chart_spec",
                    TrajectoryStatus.COMPLETED,
                    "Validated chart specification generated.",
                    started,
                ),
            ),
        }
    )
    return update


def _route_after_chart(state: AgentState) -> Literal["merge_evidence", "finalize_response"]:
    if state["status"] in {AgentRunStatus.FAILED, AgentRunStatus.ABSTAINED}:
        return "finalize_response"
    return "merge_evidence"


def _merge_evidence(state: AgentState) -> dict[str, object]:
    started = time.monotonic()
    evidence = _evidence_from_state(state)
    if not evidence:
        error = _agent_error(
            "merge_evidence",
            "no_usable_evidence",
            "No usable evidence was available for answer generation.",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        return {
            "status": AgentRunStatus.ABSTAINED,
            "evidence": (),
            "errors": (error,),
            "trajectory": (_failed_event("merge_evidence", started),),
        }
    return {
        "evidence": evidence,
        "trajectory": (
            _event(
                "merge_evidence",
                TrajectoryStatus.COMPLETED,
                "Typed evidence was merged.",
                started,
                details={"evidence_count": len(evidence)},
            ),
        ),
    }


def _route_after_merge(state: AgentState) -> Literal["generate_answer", "finalize_response"]:
    return (
        "finalize_response"
        if state["status"] in {AgentRunStatus.FAILED, AgentRunStatus.ABSTAINED}
        else "generate_answer"
    )


def _generate_answer(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    started = time.monotonic()
    context = json.dumps(
        [
            EvidenceEnvelope.model_validate(item).model_dump(mode="json")
            for item in state.get("evidence", ())
        ],
        sort_keys=True,
    )
    conversation = json.dumps(
        [message.model_dump(mode="json") for message in state["messages"]],
        sort_keys=True,
    )
    messages = (
        ModelMessage(
            role="system",
            content=(
                "Answer only from the supplied evidence. Preserve the language of the user's "
                "question. Add an inline [evidence_id] marker to every factual statement. Never "
                "invent citation IDs and do not reveal hidden reasoning. If evidence is partial, "
                "state the limitation explicitly."
            ),
        ),
        ModelMessage(
            role="user",
            content=(
                f"Conversation: {conversation}\nQuestion: {state['question']}\nEvidence: {context}"
            ),
        ),
    )
    text, attempts, error = _generate_text_with_retries(
        runtime.context.model_provider,
        messages,
        purpose=ModelPurpose.ANSWER,
        max_retries=state["policy"].max_retries_per_node,
        node="generate_answer",
    )
    update = _model_node_update("generate_answer", attempts, started, error)
    if error is not None:
        update["status"] = _terminal_model_status(error)
    else:
        update["draft_answer"] = text
    return update


def _route_after_answer(state: AgentState) -> Literal["validate_citations", "finalize_response"]:
    return "validate_citations" if state.get("draft_answer") else "finalize_response"


def _validate_citations(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    started = time.monotonic()
    answer = state.get("draft_answer") or ""
    registry = EvidenceRegistry(state.get("evidence", ()))
    known = {item.evidence_id: item for item in registry.records()}
    plan = state.get("execution_plan")
    citations_required = plan.requires_citations if plan is not None else True
    claims = extract_claims(answer)
    validation = AnswerValidator(
        registry,
        semantic_judge=runtime.context.semantic_support_judge,
    ).validate(
        answer,
        citations_required=citations_required,
    )
    citations = tuple(
        CitationReference(
            evidence_id=item,
            label=known[item].summary[:120],
            claim_ids=tuple(claim.claim_id for claim in claims if item in claim.evidence_ids),
        )
        for item in validation.cited_evidence_ids
    )
    previews = registry.hydrate_sources(runtime.context.source_checker)
    semantic_results = tuple(
        claim.semantic_support for claim in validation.claims if claim.semantic_support is not None
    )
    return {
        "answer_validation": validation,
        "claims": claims,
        "citations": citations,
        "source_previews": previews,
        "trajectory": (
            _event(
                "validate_citations",
                TrajectoryStatus.COMPLETED if validation.valid else TrajectoryStatus.FAILED,
                (
                    "Claim evidence validated."
                    if validation.valid
                    else "Claim evidence was invalid."
                ),
                started,
                details={
                    "claims": len(claims),
                    "citations": len(citations),
                    "issues": len(validation.issues),
                    "semantic_supported": sum(
                        item.status is SemanticSupportStatus.SUPPORTED for item in semantic_results
                    ),
                    "semantic_unsupported": sum(
                        item.status is SemanticSupportStatus.UNSUPPORTED
                        for item in semantic_results
                    ),
                    "semantic_unavailable": sum(
                        item.status is SemanticSupportStatus.UNAVAILABLE
                        for item in semantic_results
                    ),
                },
            ),
        ),
    }


def _route_after_validation(
    state: AgentState,
) -> Literal["finalize_response", "repair_or_abstain"]:
    validation = state.get("answer_validation")
    return (
        "finalize_response"
        if validation is not None and validation.valid
        else ("repair_or_abstain")
    )


def _repair_or_abstain(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    started = time.monotonic()
    attempts_used = state.get("repair_attempts", 0)
    if attempts_used >= state["policy"].max_repair_attempts:
        exhausted_error = _agent_error(
            "repair_or_abstain",
            "citation_repair_exhausted",
            "The answer could not be repaired within the configured limit.",
            category=AgentErrorCategory.BUDGET,
            severity=AgentErrorSeverity.TERMINAL,
        )
        return {
            "status": AgentRunStatus.ABSTAINED,
            "errors": (exhausted_error,),
            "trajectory": (_failed_event("repair_or_abstain", started),),
        }
    validation = state.get("answer_validation")
    evidence_ids = [item.evidence_id for item in state.get("evidence", ())]
    messages = (
        ModelMessage(
            role="system",
            content=(
                "Repair the draft so every material factual claim is directly supported by its "
                "inline evidence IDs. Correct or remove unsupported claims, company/period/unit "
                "mismatches, and unsupported numbers. Use only the supplied evidence, preserve "
                "the user's language, and return the complete repaired answer without reasoning."
            ),
        ),
        ModelMessage(
            role="user",
            content=json.dumps(
                {
                    "draft": state.get("draft_answer"),
                    "validation_reason_codes": validation.reason_codes if validation else (),
                    "validation_issues": (
                        [issue.model_dump(mode="json") for issue in validation.issues]
                        if validation
                        else []
                    ),
                    "evidence": [
                        EvidenceEnvelope.model_validate(item).model_dump(mode="json")
                        for item in state.get("evidence", ())
                    ],
                    "allowed_evidence_ids": evidence_ids,
                },
                sort_keys=True,
            ),
        ),
    )
    text, attempts, error = _generate_text_with_retries(
        runtime.context.model_provider,
        messages,
        purpose=ModelPurpose.REPAIR,
        max_retries=state["policy"].max_retries_per_node,
        node="repair_or_abstain",
    )
    update = _model_node_update("repair_or_abstain", attempts, started, error)
    update["repair_attempts"] = attempts_used + 1
    if error is not None:
        update["status"] = AgentRunStatus.ABSTAINED
    else:
        update["draft_answer"] = text
    return update


def _route_after_repair(
    state: AgentState,
) -> Literal["validate_citations", "finalize_response"]:
    return (
        "finalize_response"
        if state["status"] in {AgentRunStatus.FAILED, AgentRunStatus.ABSTAINED}
        else "validate_citations"
    )


def _finalize_response(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    started = time.monotonic()
    status = state["status"]
    validation = state.get("answer_validation")
    answer = state.get("draft_answer")
    memory = _updated_session_memory(state, runtime.context.max_cached_source_results)
    if status in {AgentRunStatus.RUNNING, AgentRunStatus.PARTIAL}:
        if answer and validation is not None and validation.valid:
            final_status = (
                AgentRunStatus.PARTIAL
                if status is AgentRunStatus.PARTIAL
                else AgentRunStatus.COMPLETED
            )
            return {
                "status": final_status,
                "final_answer": answer,
                "messages": (
                    SessionMessage(role="assistant", content=answer, created_at=datetime.now(UTC)),
                ),
                "session_memory": memory,
                "trajectory": (
                    _event(
                        "finalize_response",
                        TrajectoryStatus.COMPLETED,
                        "Research response finalized.",
                        started,
                    ),
                ),
            }
        status = AgentRunStatus.ABSTAINED
    return {
        "status": status,
        "final_answer": None,
        "session_memory": memory,
        "trajectory": (
            _event(
                "finalize_response",
                TrajectoryStatus.COMPLETED,
                "Research run finalized without a generated answer.",
                started,
            ),
        ),
    }


def _updated_session_memory(state: AgentState, cache_limit: int) -> SessionMemory:
    previous = state.get("session_memory") or SessionMemory()
    cached = {
        (item.kind, item.request_fingerprint): item for item in previous.cached_source_results
    }
    plan = state.get("execution_plan")
    branches = {branch.branch_id: branch for branch in plan.branches} if plan else {}
    stored_at = datetime.now(UTC)
    for retrieval in state.get("retrieval_results", ()):
        branch = branches.get(retrieval.branch_id)
        if isinstance(branch, DocumentRetrievalBranch) and retrieval.result.context:
            entry = CachedSourceResult(
                kind=branch.kind,
                request_fingerprint=_source_request_fingerprint(branch),
                stored_at=stored_at,
                retrieval_result=retrieval.result,
            )
            cached[(entry.kind, entry.request_fingerprint)] = entry
    for financial in state.get("financial_results", ()):
        branch = branches.get(financial.branch_id)
        if isinstance(branch, FinancialFactsBranch) and financial.result.observations:
            entry = CachedSourceResult(
                kind=branch.kind,
                request_fingerprint=_source_request_fingerprint(branch),
                stored_at=stored_at,
                financial_result=financial.result,
            )
            cached[(entry.kind, entry.request_fingerprint)] = entry
    for macro in state.get("macro_results", ()):
        branch = branches.get(macro.branch_id)
        if isinstance(branch, MacroSeriesBranch) and macro.result.observations:
            entry = CachedSourceResult(
                kind=branch.kind,
                request_fingerprint=_source_request_fingerprint(branch),
                stored_at=stored_at,
                macro_result=macro.result,
            )
            cached[(entry.kind, entry.request_fingerprint)] = entry
    entries = tuple(sorted(cached.values(), key=lambda item: item.stored_at)[-cache_limit:])
    return SessionMemory(
        last_resolved_query=state.get("resolved_query") or previous.last_resolved_query,
        last_execution_plan=plan or previous.last_execution_plan,
        cached_source_results=entries,
        evidence=state.get("evidence", ()) or previous.evidence,
        updated_at=stored_at,
    )


def _normalize_and_validate_plan(
    plan: ExecutionPlan,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    policy: ExecutionPolicy,
    *,
    retrieval_index_name: str,
    retrieval_index_version: str,
) -> ExecutionPlan:
    if plan.route is not analysis.route:
        raise ValueError("Plan route must match question analysis.")
    normalized: list[ExecutionBranch] = []
    for branch in plan.branches:
        if isinstance(branch, DocumentRetrievalBranch):
            retrieval_request = branch.request.model_copy(
                update={
                    "index_name": retrieval_index_name,
                    "index_version": retrieval_index_version,
                }
            )
            branch = branch.model_copy(update={"request": retrieval_request})
        if (
            isinstance(branch, FinancialFactsBranch)
            and not branch.request.company_ids
            and not branch.request.tickers
            and len(resolved.company_ids) == 1
        ):
            financial_request = branch.request.model_copy(
                update={"company_ids": resolved.company_ids}
            )
            branch = branch.model_copy(update={"request": financial_request})
        normalized.append(branch)
    plan = plan.model_copy(update={"branches": tuple(normalized)})
    if len([item for item in plan.branches if isinstance(item, ChartBranch)]) > 1:
        raise ValueError("Only one chart branch is supported.")
    source = _source_branches(plan)
    if len(source) > policy.max_tool_calls:
        raise ValueError("Execution plan exceeds the tool-call budget.")
    known_company_ids = set(resolved.company_ids)
    for branch in plan.branches:
        if (
            isinstance(branch, FinancialFactsBranch)
            and set(branch.request.company_ids) - known_company_ids
        ):
            raise ValueError("Financial plan contains an unresolved company ID.")
        if branch.kind in SOURCE_KINDS and branch.depends_on:
            raise ValueError("Source branches must be independent.")
    by_id = {item.branch_id: item for item in plan.branches}
    for branch in plan.branches:
        if isinstance(branch, CalculationBranch):
            if set(branch.depends_on) != set(branch.input_refs):
                raise ValueError("Calculation dependencies must equal input references.")
            for reference in branch.input_refs:
                source_branch = by_id[reference]
                if not isinstance(source_branch, (FinancialFactsBranch, MacroSeriesBranch)):
                    raise ValueError("Calculations require numeric source branches.")
                _validate_single_series_request(source_branch)
        if isinstance(branch, ChartBranch):
            if branch.depends_on != (branch.dataset_ref,):
                raise ValueError("Chart dependency must equal its dataset reference.")
            if not isinstance(
                by_id[branch.dataset_ref],
                (FinancialFactsBranch, MacroSeriesBranch, CalculationBranch),
            ):
                raise ValueError("Chart requires a numeric dataset reference.")
    _validate_route_shape(plan)
    represented = _represented_capabilities(plan)
    if not set(analysis.required_capabilities).issubset(represented):
        raise ValueError("Execution plan does not implement all required capabilities.")
    return plan


def _reconcile_analysis_with_plan(
    analysis: QuestionAnalysis,
    plan: ExecutionPlan,
) -> QuestionAnalysis:
    """Make a concrete supported plan authoritative over an inconsistent model classification."""

    if (
        analysis.route in {ResearchRoute.UNSUPPORTED, ResearchRoute.HYBRID}
        or plan.route is ResearchRoute.UNSUPPORTED
        or analysis.chart_requested
        or AgentCapability.CHART in analysis.required_capabilities
    ):
        return analysis
    represented = _represented_capabilities(plan)
    ordered_capabilities = tuple(
        capability for capability in AgentCapability if capability in represented
    )
    chart_requested = AgentCapability.CHART in represented
    if (
        analysis.route is plan.route
        and analysis.required_capabilities == ordered_capabilities
        and analysis.chart_requested is chart_requested
    ):
        return analysis
    return analysis.model_copy(
        update={
            "route": plan.route,
            "required_capabilities": ordered_capabilities,
            "chart_requested": chart_requested,
            "reason_codes": tuple(
                dict.fromkeys((*analysis.reason_codes, "reconciled_to_valid_plan"))
            ),
        }
    )


def _canonicalize_plan_route(plan: ExecutionPlan) -> ExecutionPlan:
    """Derive route semantics from concrete source and calculation branches."""

    source_kinds = {item.kind for item in _source_branches(plan)}
    has_calculation = any(isinstance(item, CalculationBranch) for item in plan.branches)
    route: ResearchRoute | None = None
    if len(source_kinds) >= 2:
        route = ResearchRoute.HYBRID
    elif has_calculation:
        route = ResearchRoute.CALCULATION
    elif source_kinds == {"retrieve_documents"}:
        route = ResearchRoute.RAG_ONLY
    elif source_kinds == {"query_financial_facts"}:
        route = ResearchRoute.STRUCTURED_ONLY
    elif source_kinds == {"query_macro_series"}:
        route = ResearchRoute.API_ONLY
    if route is None or route is plan.route:
        return plan
    return plan.model_copy(update={"route": route})


def _domain_execution_plan(model_plan: ModelExecutionPlan) -> ExecutionPlan:
    branches: list[ExecutionBranch] = []
    for item in model_plan.branches:
        branches.append(_domain_execution_branch(item))
    return ExecutionPlan(
        route=model_plan.route,
        branches=tuple(branches),
        requires_citations=model_plan.requires_citations,
        reason_codes=model_plan.reason_codes,
    )


def _domain_execution_branch(item: ModelExecutionBranch) -> ExecutionBranch:
    if item.kind == "retrieve_documents":
        if item.retrieval_request is None:
            raise ValueError("Retrieval branch requires retrieval_request.")
        return DocumentRetrievalBranch(
            branch_id=item.branch_id,
            depends_on=item.depends_on,
            optional=item.optional,
            request=item.retrieval_request,
        )
    if item.kind == "query_financial_facts":
        if item.financial_request is None:
            raise ValueError("Financial branch requires financial_request.")
        return FinancialFactsBranch(
            branch_id=item.branch_id,
            depends_on=item.depends_on,
            optional=item.optional,
            request=item.financial_request,
        )
    if item.kind == "query_macro_series":
        if item.macro_request is None:
            raise ValueError("Macro branch requires macro_request.")
        return MacroSeriesBranch(
            branch_id=item.branch_id,
            depends_on=item.depends_on,
            optional=item.optional,
            request=item.macro_request,
        )
    if item.kind == "calculate_metrics":
        if item.operation is None:
            raise ValueError("Calculation branch requires operation.")
        return CalculationBranch(
            branch_id=item.branch_id,
            depends_on=item.depends_on,
            optional=item.optional,
            operation=item.operation,
            input_refs=item.input_refs,
            years=Decimal(str(item.years)) if item.years is not None else None,
            window=item.window,
            base=Decimal(str(item.base)),
        )
    if item.chart_type is None or item.dataset_ref is None or item.title is None:
        raise ValueError("Chart branch requires chart fields.")
    return ChartBranch(
        branch_id=item.branch_id,
        depends_on=item.depends_on,
        optional=item.optional,
        chart_type=item.chart_type,
        dataset_ref=item.dataset_ref,
        title=item.title,
        x_label=item.x_label,
    )


def _validate_single_series_request(
    branch: FinancialFactsBranch | MacroSeriesBranch,
) -> None:
    if isinstance(branch, MacroSeriesBranch):
        if len(branch.request.series_ids) != 1:
            raise ValueError("Numeric macro branches must select exactly one series.")
        return
    company_selectors = len(branch.request.company_ids) + len(branch.request.tickers)
    if len(branch.request.metrics) != 1 or company_selectors != 1:
        raise ValueError("Numeric financial branches must select one company and one metric.")


def _validate_route_shape(plan: ExecutionPlan) -> None:
    source_kinds = {item.kind for item in _source_branches(plan)}
    if plan.route is ResearchRoute.UNSUPPORTED:
        if plan.branches:
            raise ValueError("Unsupported plans must be empty.")
        return
    if not source_kinds:
        raise ValueError("Supported plans require a source branch.")
    if plan.route is ResearchRoute.RAG_ONLY and source_kinds != {"retrieve_documents"}:
        raise ValueError("RAG-only plans may only retrieve documents.")
    if plan.route is ResearchRoute.STRUCTURED_ONLY and source_kinds != {"query_financial_facts"}:
        raise ValueError("Structured-only plans require financial facts.")
    if plan.route is ResearchRoute.API_ONLY and source_kinds != {"query_macro_series"}:
        raise ValueError("API-only plans require macro series.")
    if plan.route is ResearchRoute.CALCULATION and not any(
        isinstance(item, CalculationBranch) for item in plan.branches
    ):
        raise ValueError("Calculation routes require a calculation branch.")
    if plan.route is ResearchRoute.HYBRID and len(source_kinds) < 2:
        raise ValueError("Hybrid plans require at least two source kinds.")


def _represented_capabilities(plan: ExecutionPlan) -> set[AgentCapability]:
    represented: set[AgentCapability] = set()
    mapping = {
        "retrieve_documents": AgentCapability.DOCUMENTS,
        "query_financial_facts": AgentCapability.FINANCIAL_FACTS,
        "query_macro_series": AgentCapability.MACRO_SERIES,
        "calculate_metrics": AgentCapability.CALCULATIONS,
        "generate_chart_spec": AgentCapability.CHART,
    }
    for branch in plan.branches:
        represented.add(mapping[branch.kind])
    return represented


def _source_branch_max_attempts(state: AgentState, branch_id: str) -> int:
    plan = state["execution_plan"]
    if plan is None:
        return 1
    branches = _source_branches(plan)
    extra = state["policy"].max_tool_calls - len(branches)
    for branch in branches:
        allocated = min(state["policy"].max_retries_per_node, max(0, extra))
        if branch.branch_id == branch_id:
            return 1 + allocated
        extra -= allocated
    return 1


def _source_branches(
    plan: ExecutionPlan,
) -> tuple[DocumentRetrievalBranch | FinancialFactsBranch | MacroSeriesBranch, ...]:
    return tuple(
        item
        for item in plan.branches
        if isinstance(item, (DocumentRetrievalBranch, FinancialFactsBranch, MacroSeriesBranch))
    )


def _source_request_fingerprint(
    branch: DocumentRetrievalBranch | FinancialFactsBranch | MacroSeriesBranch,
) -> str:
    payload = json.dumps(
        {
            "kind": branch.kind,
            "request": branch.request.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _merge_follow_up_resolution(current: ResolvedQuery, previous: ResolvedQuery) -> ResolvedQuery:
    current_kinds = {entity.kind for entity in current.entities}
    inherited_entities = tuple(
        entity for entity in previous.entities if entity.kind not in current_kinds
    )
    return current.model_copy(
        update={
            "entities": (*current.entities, *inherited_entities),
            "company_ids": current.company_ids or previous.company_ids,
            "accession_numbers": current.accession_numbers or previous.accession_numbers,
            "filing_forms": current.filing_forms or previous.filing_forms,
            "fiscal_years": current.fiscal_years or previous.fiscal_years,
            "fiscal_periods": current.fiscal_periods or previous.fiscal_periods,
            "dates": current.dates or previous.dates,
            "metrics": current.metrics or previous.metrics,
        }
    )


def _branch_has_evidence(
    state: AgentState,
    branch: DocumentRetrievalBranch | FinancialFactsBranch | MacroSeriesBranch,
) -> bool:
    if isinstance(branch, DocumentRetrievalBranch):
        retrieval_result = next(
            (
                value
                for value in state.get("retrieval_results", ())
                if value.branch_id == branch.branch_id
            ),
            None,
        )
        return bool(
            retrieval_result
            and retrieval_result.result.context
            and not retrieval_result.result.trace.abstained
        )
    if isinstance(branch, FinancialFactsBranch):
        financial_result = next(
            (
                value
                for value in state.get("financial_results", ())
                if value.branch_id == branch.branch_id
            ),
            None,
        )
        return bool(financial_result and financial_result.result.observations)
    macro_result = next(
        (value for value in state.get("macro_results", ()) if value.branch_id == branch.branch_id),
        None,
    )
    return bool(macro_result and macro_result.result.observations)


def _has_any_source_evidence(state: AgentState) -> bool:
    return bool(
        any(item.result.context for item in state.get("retrieval_results", ()))
        or any(item.result.observations for item in state.get("financial_results", ()))
        or any(item.result.observations for item in state.get("macro_results", ()))
    )


def _failed_planned_branches[BranchT: ExecutionBranch](
    state: AgentState, branch_type: type[BranchT]
) -> tuple[BranchT, ...]:
    plan = state["execution_plan"]
    if plan is None:
        return ()
    outcomes = {item.branch_id: item for item in state.get("branch_outcomes", ())}
    return tuple(
        branch
        for branch in plan.branches
        if isinstance(branch, branch_type)
        and (
            branch.branch_id not in outcomes
            or outcomes[branch.branch_id].status is BranchStatus.FAILED
        )
    )


def _execute_calculation(branch: CalculationBranch, state: AgentState) -> CalculationResult:
    operation = branch.operation
    series = [
        _numeric_series(reference, state, operation=operation) for reference in branch.input_refs
    ]
    if operation == "quarter_over_quarter_growth":
        previous, current = _two_observations(series[0])
        return quarter_over_quarter_growth(current, previous)
    if operation == "year_over_year_growth":
        previous, current = _two_observations(series[0])
        return year_over_year_growth(current, previous)
    if operation == "cagr":
        start, end = _endpoints(series[0])
        assert branch.years is not None
        return compound_annual_growth_rate(end, start, years=branch.years)
    if operation == "margin":
        return margin(_latest(series[0]), _latest(series[1]))
    if operation == "absolute_change":
        previous, current = _endpoints(series[0])
        return absolute_change(current, previous)
    if operation == "percentage_change":
        previous, current = _endpoints(series[0])
        return percentage_change(current, previous)
    if operation == "rolling_average":
        assert branch.window is not None
        return rolling_average(series[0], window=branch.window)
    if operation == "normalised_index":
        return normalised_index(series[0], base=branch.base)
    return correlation(series[0], series[1])


def _numeric_series(
    branch_id: str,
    state: AgentState,
    *,
    operation: str | None = None,
) -> tuple[NumericObservation, ...]:
    financial = next(
        (item for item in state.get("financial_results", ()) if item.branch_id == branch_id),
        None,
    )
    if financial is not None:
        selected = _select_financial_observations(financial.result.observations, operation)
        observations = tuple(
            NumericObservation(
                label=f"{item.company_name} {item.metric} {item.period_end.isoformat()}",
                value=item.value,
                unit=item.unit,
                source_url=item.source_url,
                observed_at=item.period_end,
            )
            for item in selected
        )
        return tuple(sorted(observations, key=lambda item: item.observed_at or datetime.min.date()))
    macro = next(
        (item for item in state.get("macro_results", ()) if item.branch_id == branch_id),
        None,
    )
    if macro is None:
        raise ValueError("Numeric branch result is missing.")
    observations = tuple(
        NumericObservation(
            label=f"{item.series_id} {item.observed_at.isoformat()}",
            value=item.value,
            unit=item.unit,
            source_url=item.source_url,
            observed_at=item.observed_at,
        )
        for item in macro.result.observations
        if not item.is_missing
    )
    return tuple(sorted(observations, key=lambda item: item.observed_at or datetime.min.date()))


def _select_financial_observations(
    observations: Sequence[FinancialFactObservation],
    operation: str | None,
) -> tuple[FinancialFactObservation, ...]:
    deduplicated: dict[tuple[object, ...], FinancialFactObservation] = {}
    for item in observations:
        key = (
            item.company_id,
            item.metric,
            item.unit,
            item.period_start,
            item.period_end,
            item.period_type,
            item.fiscal_period,
        )
        existing = deduplicated.get(key)
        if existing is None or _financial_filing_key(item) > _financial_filing_key(existing):
            deduplicated[key] = item
    ordered = tuple(
        sorted(
            deduplicated.values(),
            key=lambda item: (item.period_end, *_financial_filing_key(item)),
        )
    )
    if operation not in {"year_over_year_growth", "quarter_over_quarter_growth"}:
        return ordered
    series_keys = {(item.company_id, item.metric, item.unit) for item in ordered}
    if len(series_keys) != 1:
        raise ValueError("Growth requires exactly one company, metric, and unit series.")
    if operation == "quarter_over_quarter_growth":
        quarters = tuple(item for item in ordered if item.period_type == "quarter")
        if len(quarters) < 2:
            raise ValueError("Quarter-over-quarter growth requires two quarterly observations.")
        return quarters[-2:]
    annual = tuple(item for item in ordered if item.period_type == "annual")
    if len(annual) >= 2:
        return annual[-2:]
    comparable = tuple(item for item in ordered if item.period_type in {"quarter", "year_to_date"})
    if len(comparable) < 2:
        raise ValueError("Year-over-year growth requires two comparable observations.")
    current = comparable[-1]
    previous = next(
        (item for item in reversed(comparable[:-1]) if _same_reporting_period(item, current)),
        None,
    )
    if previous is None:
        raise ValueError("Year-over-year growth requires matching reporting periods.")
    return previous, current


def _financial_filing_key(item: FinancialFactObservation) -> tuple[date, str, str]:
    return item.filed_date or date.min, item.accession_number or "", str(item.id)


def _same_reporting_period(
    previous: FinancialFactObservation,
    current: FinancialFactObservation,
) -> bool:
    if previous.period_type != current.period_type:
        return False
    if previous.fiscal_period and current.fiscal_period:
        return previous.fiscal_period == current.fiscal_period
    return (previous.period_end.month, previous.period_end.day) == (
        current.period_end.month,
        current.period_end.day,
    )


def _two_observations(
    observations: Sequence[NumericObservation],
) -> tuple[NumericObservation, NumericObservation]:
    if len(observations) != 2:
        raise ValueError("Calculation requires exactly two ordered observations.")
    return observations[0], observations[1]


def _endpoints(
    observations: Sequence[NumericObservation],
) -> tuple[NumericObservation, NumericObservation]:
    if len(observations) < 2:
        raise ValueError("Calculation requires at least two observations.")
    return observations[0], observations[-1]


def _latest(observations: Sequence[NumericObservation]) -> NumericObservation:
    if len(observations) != 1:
        raise ValueError("Scalar calculation input must contain exactly one observation.")
    return observations[0]


def _chart_dataset(reference: str, state: AgentState) -> ValidatedChartDataset:
    observations = _numeric_series_for_chart(reference, state)
    if observations is not None:
        if not observations:
            raise ValueError("Chart source has no observations.")
        units = {item.unit for item in observations}
        if len(units) != 1:
            raise ValueError("Chart source contains incompatible units.")
        key = reference
        return ValidatedChartDataset(
            series=(ChartSeries(key=key, label=observations[0].label, unit=units.pop()),),
            points=tuple(
                ChartPoint(
                    x=item.observed_at,
                    values={key: item.value},
                    source_urls=(item.source_url,),
                )
                for item in observations
                if item.observed_at is not None and item.value is not None
            ),
        )
    calculation = next(
        (item for item in state.get("calculations", ()) if item.branch_id == reference),
        None,
    )
    if calculation is None:
        raise ValueError("Chart dataset reference is missing.")
    if any(point.observed_at is None for point in calculation.result.values):
        raise ValueError("Scalar calculations without dates cannot be charted.")
    return ValidatedChartDataset(
        series=(
            ChartSeries(
                key=reference,
                label=calculation.result.operation,
                unit=calculation.result.unit,
            ),
        ),
        points=tuple(
            ChartPoint(
                x=cast(date, point.observed_at),
                values={reference: point.value},
                source_urls=calculation.result.sources,
            )
            for point in calculation.result.values
        ),
    )


def _numeric_series_for_chart(
    reference: str, state: AgentState
) -> tuple[NumericObservation, ...] | None:
    if any(item.branch_id == reference for item in state.get("financial_results", ())):
        return _numeric_series(reference, state)
    if any(item.branch_id == reference for item in state.get("macro_results", ())):
        return _numeric_series(reference, state)
    return None


def _evidence_from_state(state: AgentState) -> tuple[EvidenceEnvelope, ...]:
    evidence: list[EvidenceEnvelope] = []
    for retrieval_branch in state.get("retrieval_results", ()):
        for context_item in retrieval_branch.result.context:
            evidence.append(
                EvidenceEnvelope(
                    evidence_id=context_item.citation_label,
                    kind=EvidenceKind.DOCUMENT,
                    summary=context_item.content,
                    source_urls=(context_item.source_url,),
                    lineage_refs=(retrieval_branch.branch_id, context_item.source_id),
                    metadata=EvidenceMetadata(
                        company_id=context_item.company_id,
                        company_name=context_item.company_name,
                        document_version_id=context_item.document_version_id,
                        section_id=context_item.section_id,
                        chunk_id=context_item.chunk_id,
                        financial_fact_id=context_item.financial_fact_id,
                        fiscal_year=context_item.fiscal_year,
                        fiscal_period=context_item.fiscal_period,
                        page_start=context_item.page_start,
                        page_end=context_item.page_end,
                    ),
                    payload=context_item.model_dump(mode="json"),
                )
            )
    for financial_branch in state.get("financial_results", ()):
        for fact in financial_branch.result.observations:
            evidence.append(
                EvidenceEnvelope(
                    evidence_id=f"financial_fact:{fact.id}",
                    kind=EvidenceKind.FINANCIAL_FACT,
                    summary=(
                        f"{fact.company_name} {fact.metric}: {fact.value} {fact.unit} "
                        f"at {fact.period_end.isoformat()}"
                    ),
                    source_urls=(fact.source_url,),
                    lineage_refs=(financial_branch.branch_id,),
                    metadata=EvidenceMetadata(
                        company_id=fact.company_id,
                        company_name=fact.company_name,
                        financial_fact_id=fact.id,
                        metric=fact.metric,
                        period_start=fact.period_start,
                        period_end=fact.period_end,
                        fiscal_year=fact.fiscal_year,
                        fiscal_period=fact.fiscal_period,
                        unit=fact.unit,
                        value=fact.value,
                    ),
                    payload=fact.model_dump(mode="json"),
                )
            )
    for macro_branch in state.get("macro_results", ()):
        for observation in macro_branch.result.observations:
            if observation.is_missing or observation.value is None:
                continue
            evidence.append(
                EvidenceEnvelope(
                    evidence_id=(
                        f"macro:{observation.series_id.lower()}:"
                        f"{observation.observed_at.isoformat()}"
                    ),
                    kind=EvidenceKind.MACRO_OBSERVATION,
                    summary=(
                        f"{observation.series_id}: {observation.value} {observation.unit} "
                        f"at {observation.observed_at.isoformat()}"
                    ),
                    source_urls=(observation.source_url,),
                    lineage_refs=(macro_branch.branch_id,),
                    metadata=EvidenceMetadata(
                        macro_observation_id=observation.id,
                        period_start=observation.observed_at,
                        period_end=observation.observed_at,
                        unit=observation.unit,
                        value=observation.value,
                    ),
                    payload=observation.model_dump(mode="json"),
                )
            )
    plan = state.get("execution_plan")
    calculations_by_id = {item.branch_id: item for item in state.get("calculations", ())}
    for branch_id, calculation in calculations_by_id.items():
        plan_branch = (
            next(
                (
                    branch
                    for branch in plan.branches
                    if isinstance(branch, CalculationBranch) and branch.branch_id == branch_id
                ),
                None,
            )
            if plan
            else None
        )
        input_evidence_ids = _input_evidence_ids(
            plan_branch.input_refs if plan_branch else (), state
        )
        result_value = (
            calculation.result.values[0].value if len(calculation.result.values) == 1 else None
        )
        evidence.append(
            EvidenceEnvelope(
                evidence_id=f"calculation:{branch_id}",
                kind=EvidenceKind.CALCULATION,
                summary=(
                    f"{calculation.result.operation}: "
                    f"{calculation.result.model_dump(mode='json')['values']}"
                ),
                source_urls=calculation.result.sources,
                lineage_refs=input_evidence_ids,
                metadata=EvidenceMetadata(
                    unit=calculation.result.unit,
                    value=result_value,
                    formula=calculation.result.formula,
                    operation=calculation.result.operation,
                ),
                payload=calculation.result.model_dump(mode="json"),
            )
        )
    deduplicated = {item.evidence_id: item for item in evidence}
    return tuple(deduplicated[key] for key in sorted(deduplicated))


def _input_evidence_ids(references: tuple[str, ...], state: AgentState) -> tuple[str, ...]:
    evidence_ids: list[str] = []
    retrieval_by_branch = {
        item.branch_id: item.result for item in state.get("retrieval_results", ())
    }
    financial_by_branch = {
        item.branch_id: item.result for item in state.get("financial_results", ())
    }
    macro_by_branch = {item.branch_id: item.result for item in state.get("macro_results", ())}
    calculation_branches = {item.branch_id for item in state.get("calculations", ())}
    for reference in references:
        if reference in retrieval_by_branch:
            evidence_ids.extend(
                item.citation_label for item in retrieval_by_branch[reference].context
            )
        elif reference in financial_by_branch:
            evidence_ids.extend(
                f"financial_fact:{item.id}" for item in financial_by_branch[reference].observations
            )
        elif reference in macro_by_branch:
            evidence_ids.extend(
                f"macro:{item.series_id.lower()}:{item.observed_at.isoformat()}"
                for item in macro_by_branch[reference].observations
                if not item.is_missing and item.value is not None
            )
        elif reference in calculation_branches:
            evidence_ids.append(f"calculation:{reference}")
    return tuple(dict.fromkeys(evidence_ids))


def _generate_structured_with_retries[OutputT: BaseModel](
    provider: ResearchModelProvider,
    messages: Sequence[ModelMessage],
    output_type: type[OutputT],
    *,
    purpose: ModelPurpose,
    max_retries: int,
    node: str,
) -> tuple[OutputT | None, int, AgentError | None]:
    attempts = 0
    for attempt in range(1, max_retries + 2):
        attempts = attempt
        try:
            result = provider.generate_structured(messages, output_type, purpose=purpose)
        except ModelProviderError as exc:
            error = exc.error.model_copy(update={"node": node, "attempt": attempt})
            if error.recoverable and attempt <= max_retries:
                continue
            return None, attempts, error
        if result.refusal is not None:
            return None, attempts, _provider_refusal(node, attempt)
        return result.output, attempts, None
    raise AssertionError("Unreachable model retry state.")


def _generate_text_with_retries(
    provider: ResearchModelProvider,
    messages: Sequence[ModelMessage],
    *,
    purpose: ModelPurpose,
    max_retries: int,
    node: str,
) -> tuple[str | None, int, AgentError | None]:
    attempts = 0
    for attempt in range(1, max_retries + 2):
        attempts = attempt
        try:
            result = provider.generate_text(messages, purpose=purpose)
        except ModelProviderError as exc:
            error = exc.error.model_copy(update={"node": node, "attempt": attempt})
            if error.recoverable and attempt <= max_retries:
                continue
            return None, attempts, error
        if result.refusal is not None:
            return None, attempts, _provider_refusal(node, attempt)
        return result.text, attempts, None
    raise AssertionError("Unreachable model retry state.")


def _model_node_update(
    node: str,
    attempts: int,
    started: float,
    error: AgentError | None,
) -> dict[str, object]:
    update: dict[str, object] = {
        "node_attempts": (NodeAttempt(node=node, attempts=attempts),),
        "trajectory": (
            _event(
                node,
                TrajectoryStatus.FAILED if error else TrajectoryStatus.COMPLETED,
                "Model operation failed." if error else "Model operation completed.",
                started,
                details={"attempts": attempts},
            ),
        ),
    }
    if error is not None:
        update["errors"] = (error,)
    return update


def _terminal_model_status(error: AgentError) -> AgentRunStatus:
    return (
        AgentRunStatus.ABSTAINED
        if error.category is AgentErrorCategory.PROVIDER_REFUSAL
        else AgentRunStatus.FAILED
    )


def _provider_refusal(node: str, attempt: int) -> AgentError:
    return AgentError(
        category=AgentErrorCategory.PROVIDER_REFUSAL,
        severity=AgentErrorSeverity.TERMINAL,
        code="model_refusal",
        message="The model declined the requested operation.",
        node=node,
        attempt=attempt,
    )


def _validation_error(node: str, code: str) -> AgentError:
    return AgentError(
        category=AgentErrorCategory.VALIDATION,
        severity=AgentErrorSeverity.TERMINAL,
        code=code,
        message="The research workflow received an invalid typed state or plan.",
        node=node,
    )


def _agent_error(
    node: str,
    code: str,
    message: str,
    *,
    category: AgentErrorCategory = AgentErrorCategory.TOOL,
    severity: AgentErrorSeverity = AgentErrorSeverity.RECOVERABLE,
    attempt: int = 1,
) -> AgentError:
    return AgentError(
        category=category,
        severity=severity,
        code=code,
        message=message,
        node=node,
        attempt=attempt,
    )


def _event(
    node: str,
    status: TrajectoryStatus,
    summary: str,
    started: float,
    *,
    details: dict[str, str | int | float | bool | None] | None = None,
) -> TrajectoryEvent:
    return TrajectoryEvent(
        node=node,
        status=status,
        occurred_at=datetime.now(UTC),
        summary=summary,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        details=details or {},
    )


def _failed_event(node: str, started: float) -> TrajectoryEvent:
    return _event(node, TrajectoryStatus.FAILED, "Workflow node failed.", started)


def _skipped(node: str) -> dict[str, object]:
    return {
        "trajectory": (
            TrajectoryEvent(
                node=node,
                status=TrajectoryStatus.SKIPPED,
                occurred_at=datetime.now(UTC),
                summary="Workflow node was skipped.",
            ),
        )
    }
