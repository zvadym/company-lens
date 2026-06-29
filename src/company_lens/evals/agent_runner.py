from __future__ import annotations

import re
import uuid
from typing import Protocol, cast

from company_lens.agent.schemas import (
    AgentState,
    CalculationBranch,
    ExecutionPlan,
    ExecutionPolicy,
    ResearchFrame,
    ResearchRoute,
)
from company_lens.evals.deterministic import (
    ObservedCaseResult,
    ObservedCompany,
    ObservedGoldenResults,
    ObservedTrajectoryEvent,
)
from company_lens.evals.golden import (
    ExpectedRoute,
    ExpectedTool,
    GoldenDataset,
    GoldenDatasetCase,
)
from company_lens.retrieval.adaptive_schemas import ResolvedQuery


class GoldenResearchAgent(Protocol):
    def run(self, question: str, *, session_id: str, policy: ExecutionPolicy) -> AgentState: ...


def run_golden_agent_dataset(
    dataset: GoldenDataset,
    agent: GoldenResearchAgent,
    *,
    policy: ExecutionPolicy,
    max_cases: int | None = None,
    case_ids: tuple[str, ...] = (),
    session_prefix: str = "golden-eval",
    run_token: str | None = None,
) -> ObservedGoldenResults:
    cases = _selected_cases(dataset, case_ids=case_ids, max_cases=max_cases)
    token = run_token or uuid.uuid4().hex[:12]
    results = tuple(
        _run_case(
            case,
            agent,
            policy=policy,
            session_id=_case_session_id(session_prefix, token, case.id),
        )
        for case in cases
    )
    return ObservedGoldenResults(
        schema_version=1,
        dataset_name=dataset.name,
        dataset_version=dataset.version,
        results=results,
    )


def _selected_cases(
    dataset: GoldenDataset,
    *,
    case_ids: tuple[str, ...],
    max_cases: int | None,
) -> tuple[GoldenDatasetCase, ...]:
    if max_cases is not None and max_cases < 1:
        raise ValueError("max_cases must be at least 1")
    by_id = {case.id: case for case in dataset.cases}
    if case_ids:
        missing = sorted(set(case_ids) - set(by_id))
        if missing:
            raise ValueError(f"unknown golden case ids: {', '.join(missing)}")
        selected = tuple(by_id[case_id] for case_id in case_ids)
    else:
        selected = dataset.cases
    return selected[:max_cases] if max_cases is not None else selected


def _run_case(
    case: GoldenDatasetCase,
    agent: GoldenResearchAgent,
    *,
    policy: ExecutionPolicy,
    session_id: str,
) -> ObservedCaseResult:
    user_turns = [turn for turn in case.conversation if turn.role == "user"]
    if len(user_turns) != len(case.conversation):
        raise ValueError(f"{case.id} contains assistant turns, which the live runner cannot seed")

    state: AgentState | None = None
    for turn in user_turns:
        state = agent.run(turn.content, session_id=session_id, policy=policy)
    if state is None:
        raise ValueError(f"{case.id} does not contain a user turn")
    return observed_result_from_state(case.id, state)


def observed_result_from_state(case_id: str, state: AgentState) -> ObservedCaseResult:
    frame = state.get("research_frame")
    resolved = _resolved_query(state, frame)
    plan = state.get("execution_plan")
    route = _observed_route(state, plan)
    return ObservedCaseResult(
        case_id=case_id,
        companies=_observed_companies(frame, resolved),
        metrics=resolved.metrics if resolved is not None else (),
        operation=_observed_operation(frame, plan),
        route=route,
        tools=_observed_tools(plan),
        trajectory=_observed_trajectory(state),
    )


def _resolved_query(state: AgentState, frame: ResearchFrame | None) -> ResolvedQuery | None:
    if frame is not None:
        return frame.resolved_query
    return state.get("resolved_query")


def _observed_companies(
    frame: ResearchFrame | None,
    resolved: ResolvedQuery | None,
) -> tuple[ObservedCompany, ...]:
    if frame is not None and frame.company_targets:
        return tuple(
            ObservedCompany(
                mention=target.mention,
                status=target.status,
                ticker=target.ticker,
                source=target.source,
            )
            for target in frame.company_targets
        )
    if resolved is None:
        return ()
    return tuple(
        ObservedCompany(
            mention=entity.mention,
            status=entity.status,
            ticker=None,
            source="current_question",
        )
        for entity in resolved.entities
        if entity.kind in {"company", "public_company"}
    )


def _observed_route(state: AgentState, plan: ExecutionPlan | None) -> ExpectedRoute | None:
    route: ResearchRoute | None = plan.route if plan is not None else None
    if route is None:
        analysis = state.get("analysis")
        route = analysis.route if analysis is not None else None
    return route.value if route is not None else None


def _observed_operation(frame: ResearchFrame | None, plan: ExecutionPlan | None) -> str | None:
    operations: list[str] = []
    if plan is not None:
        operations.extend(
            branch.operation for branch in plan.branches if isinstance(branch, CalculationBranch)
        )
    if not operations and frame is not None and frame.follow_up_operation is not None:
        operations.append(frame.follow_up_operation)
    unique = tuple(dict.fromkeys(operations))
    return unique[0] if len(unique) == 1 else None


def _observed_tools(plan: ExecutionPlan | None) -> tuple[ExpectedTool, ...]:
    if plan is None:
        return ()
    tools = tuple(
        cast(ExpectedTool, branch.kind)
        for branch in plan.branches
        if branch.kind
        in {
            "retrieve_documents",
            "query_financial_facts",
            "query_macro_series",
            "calculate_metrics",
            "generate_chart_spec",
        }
    )
    return tuple(dict.fromkeys(tools))


def _observed_trajectory(state: AgentState) -> tuple[ObservedTrajectoryEvent, ...]:
    return tuple(
        ObservedTrajectoryEvent(
            node=event.node,
            status=event.status.value,
        )
        for event in state.get("trajectory", ())
    )


def _case_session_id(prefix: str, run_token: str, case_id: str) -> str:
    safe_prefix = _safe_session_part(prefix) or "golden-eval"
    safe_token = _safe_session_part(run_token) or uuid.uuid4().hex[:12]
    safe_case = _safe_session_part(case_id)
    session_id = f"{safe_prefix}-{safe_token}-{safe_case}"
    return session_id[:128].rstrip(".:-_") or f"golden-eval-{uuid.uuid4().hex[:12]}"


def _safe_session_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._:-]+", "-", value.strip())
    cleaned = cleaned.strip(".:-_")
    return cleaned
