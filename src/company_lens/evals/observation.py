from __future__ import annotations

from typing import cast

from company_lens.agent.schemas import (
    AgentState,
    CalculationBranch,
    ExecutionPlan,
    ResearchFrame,
    ResearchRoute,
)
from company_lens.evals.golden import ExpectedRoute, ExpectedTool, GoldenDatasetCase
from company_lens.evals.models import (
    CaseObservation,
    CitationObservation,
    ObservedCaseResult,
    ObservedCompany,
    ObservedOperationalMetrics,
    ObservedTrajectoryEvent,
)
from company_lens.retrieval.adaptive_schemas import ResolvedQuery


def case_observation_from_state(
    case: GoldenDatasetCase,
    state: AgentState,
    *,
    operational: ObservedOperationalMetrics | None = None,
) -> CaseObservation:
    frame = state.get("research_frame")
    resolved = _resolved_query(state, frame)
    plan = state.get("execution_plan")
    citation = _citation_observation(case, state)
    failure_code = (
        "citation_validation_unavailable"
        if case.citation_mode == "required"
        and citation.answer_present
        and not citation.validation_present
        else None
    )
    return CaseObservation(
        case_id=case.id,
        outcome="infrastructure_error" if failure_code else "observed",
        failure_code=failure_code,
        companies=_observed_companies(frame, resolved),
        metrics=resolved.metrics if resolved is not None else (),
        operation=_observed_operation(frame, plan),
        route=_observed_route(state, frame, resolved, plan),
        tools=_observed_tools(plan),
        trajectory=_observed_trajectory(state),
        operational=operational,
        citation=citation,
    )


def observed_result_from_state(
    case_id: str,
    state: AgentState,
    *,
    operational: ObservedOperationalMetrics | None = None,
) -> ObservedCaseResult:
    frame = state.get("research_frame")
    resolved = _resolved_query(state, frame)
    plan = state.get("execution_plan")
    return ObservedCaseResult(
        case_id=case_id,
        companies=_observed_companies(frame, resolved),
        metrics=resolved.metrics if resolved is not None else (),
        operation=_observed_operation(frame, plan),
        route=_observed_route(state, frame, resolved, plan),
        tools=_observed_tools(plan),
        trajectory=_observed_trajectory(state),
        operational=operational,
    )


def infrastructure_case_observation(
    case: GoldenDatasetCase,
    *,
    failure_code: str,
    operational: ObservedOperationalMetrics | None = None,
) -> CaseObservation:
    return CaseObservation(
        case_id=case.id,
        outcome="infrastructure_error",
        failure_code=failure_code,
        operational=operational,
        citation=CitationObservation(
            mode=case.citation_mode,
            answer_present=False,
            validation_present=False,
        ),
    )


def observed_result_from_observation(observation: CaseObservation) -> ObservedCaseResult:
    return ObservedCaseResult(
        case_id=observation.case_id,
        companies=observation.companies,
        metrics=observation.metrics,
        operation=observation.operation,
        route=observation.route,
        tools=observation.tools,
        trajectory=observation.trajectory,
        operational=observation.operational,
    )


def _citation_observation(
    case: GoldenDatasetCase,
    state: AgentState,
) -> CitationObservation:
    answer_present = bool((state.get("final_answer") or "").strip())
    if case.citation_mode == "not_applicable":
        return CitationObservation(
            mode="not_applicable",
            answer_present=answer_present,
            validation_present=False,
        )

    validation = state.get("answer_validation")
    if not answer_present:
        reason_codes = set(validation.reason_codes if validation is not None else ())
        reason_codes.add("missing_answer")
        return CitationObservation(
            mode="required",
            answer_present=False,
            validation_present=validation is not None,
            valid=False,
            claim_count=len(validation.claims) if validation is not None else 0,
            cited_evidence_count=(
                len(validation.cited_evidence_ids) if validation is not None else 0
            ),
            unknown_evidence_ids=tuple(
                sorted(set(validation.unknown_evidence_ids if validation is not None else ()))
            ),
            reason_codes=tuple(sorted(reason_codes)),
        )
    if validation is None:
        return CitationObservation(
            mode="required",
            answer_present=True,
            validation_present=False,
        )
    return CitationObservation(
        mode="required",
        answer_present=True,
        validation_present=True,
        valid=validation.valid,
        claim_count=len(validation.claims),
        cited_evidence_count=len(validation.cited_evidence_ids),
        unknown_evidence_ids=tuple(sorted(set(validation.unknown_evidence_ids))),
        reason_codes=tuple(sorted(set(validation.reason_codes))),
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
            source="current_question",
        )
        for entity in resolved.entities
        if entity.kind in {"company", "public_company"}
    )


def _observed_route(
    state: AgentState,
    frame: ResearchFrame | None,
    resolved: ResolvedQuery | None,
    plan: ExecutionPlan | None,
) -> ExpectedRoute | None:
    if plan is None and _has_unresolved_company_target(frame, resolved):
        return ResearchRoute.UNSUPPORTED.value
    route = plan.route if plan is not None else None
    if route is None:
        analysis = state.get("analysis")
        route = analysis.route if analysis is not None else None
    return route.value if route is not None else None


def _has_unresolved_company_target(
    frame: ResearchFrame | None,
    resolved: ResolvedQuery | None,
) -> bool:
    if frame is not None and frame.company_targets:
        return any(target.status != "resolved" for target in frame.company_targets)
    if resolved is None:
        return False
    return any(
        entity.status != "resolved"
        for entity in resolved.entities
        if entity.kind in {"company", "public_company"}
    )


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
        ObservedTrajectoryEvent(node=event.node, status=event.status.value)
        for event in state.get("trajectory", ())
    )
