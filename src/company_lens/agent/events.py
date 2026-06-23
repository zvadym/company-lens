from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from company_lens.agent.schemas import (
    AgentState,
    BranchOutcome,
    CalculationBranch,
    ChartBranch,
    DocumentRetrievalBranch,
    ExecutionBranch,
    FinancialFactsBranch,
    MacroSeriesBranch,
    TrajectoryEvent,
)
from company_lens.evidence.schemas import SemanticSupportStatus

PublicAgentEventType = Literal[
    "analysis.summary",
    "entities.summary",
    "plan.summary",
    "node.status",
    "tool.status",
    "validation.summary",
    "chart.ready",
]

_MAX_WARNINGS = 10
_MAX_WARNING_CHARS = 240


@dataclass(frozen=True)
class AgentExecutionEvent:
    event_key: str
    event_type: PublicAgentEventType
    data: dict[str, object]


def project_agent_transition(
    previous: AgentState | None,
    current: AgentState,
) -> tuple[AgentExecutionEvent, ...]:
    events: list[AgentExecutionEvent] = []
    analysis = current.get("analysis")
    previous_analysis = previous.get("analysis") if previous is not None else None
    if analysis is not None and analysis != previous_analysis:
        events.append(
            AgentExecutionEvent(
                event_key=_stable_key("analysis:summary", analysis.model_dump(mode="json")),
                event_type="analysis.summary",
                data={
                    "route": analysis.route.value,
                    "required_capabilities": tuple(
                        capability.value for capability in analysis.required_capabilities
                    ),
                    "chart_requested": analysis.chart_requested,
                    "is_follow_up": analysis.is_follow_up,
                    "reason_codes": analysis.reason_codes,
                },
            )
        )

    resolved = current.get("resolved_query")
    previous_resolved = previous.get("resolved_query") if previous is not None else None
    if resolved is not None and resolved != previous_resolved:
        events.append(
            AgentExecutionEvent(
                event_key=_stable_key("entities:summary", resolved.model_dump(mode="json")),
                event_type="entities.summary",
                data={
                    "entities": tuple(
                        {
                            "kind": entity.kind,
                            "mention": entity.mention,
                            "status": entity.status,
                            "canonical_value": entity.canonical_value,
                            "candidates": tuple(
                                {
                                    "canonical_value": candidate.canonical_value,
                                    "display_value": candidate.display_value,
                                    "match_kind": candidate.match_kind,
                                }
                                for candidate in entity.candidates
                            ),
                        }
                        for entity in resolved.entities
                    ),
                    "company_ids": resolved.company_ids,
                    "accession_numbers": resolved.accession_numbers,
                    "filing_forms": resolved.filing_forms,
                    "fiscal_years": resolved.fiscal_years,
                    "fiscal_periods": resolved.fiscal_periods,
                    "dates": tuple(value.isoformat() for value in resolved.dates),
                    "metrics": resolved.metrics,
                    "has_ambiguity": resolved.has_ambiguity,
                },
            )
        )

    plan = current.get("execution_plan")
    previous_plan = previous.get("execution_plan") if previous is not None else None
    if plan is not None and plan != previous_plan:
        events.append(
            AgentExecutionEvent(
                event_key=_stable_key("plan:summary", plan.model_dump(mode="json")),
                event_type="plan.summary",
                data={
                    "route": plan.route.value,
                    "requires_citations": plan.requires_citations,
                    "reason_codes": plan.reason_codes,
                    "branches": tuple(_branch_summary(branch) for branch in plan.branches),
                },
            )
        )

    old_outcomes = previous.get("branch_outcomes", ()) if previous is not None else ()
    for outcome in current.get("branch_outcomes", ())[len(old_outcomes) :]:
        events.append(_tool_outcome_event(current, outcome))

    chart = current.get("chart_spec")
    previous_chart = previous.get("chart_spec") if previous is not None else None
    if chart is not None and chart != previous_chart:
        events.append(
            AgentExecutionEvent(
                event_key=_stable_key("chart:ready", chart.model_dump(mode="json")),
                event_type="chart.ready",
                data={
                    "chart_type": chart.chart_type,
                    "title": chart.title,
                    "series_count": len(chart.series),
                    "point_count": len(chart.data),
                    "source_count": len(chart.sources),
                },
            )
        )

    validation = current.get("answer_validation")
    previous_validation = previous.get("answer_validation") if previous is not None else None
    if validation is not None and validation != previous_validation:
        claims = current.get("claims", ())
        supported = sum(item.supported for item in validation.claims)
        semantic = tuple(
            item.semantic_support for item in validation.claims if item.semantic_support is not None
        )
        repair_attempt = current.get("repair_attempts", 0)
        events.append(
            AgentExecutionEvent(
                event_key=f"validation:summary:{repair_attempt}",
                event_type="validation.summary",
                data={
                    "valid": validation.valid,
                    "claim_count": len(claims),
                    "material_claim_count": sum(item.material for item in claims),
                    "supported_claim_count": supported,
                    "unsupported_claim_count": len(validation.claims) - supported,
                    "cited_evidence_count": len(validation.cited_evidence_ids),
                    "issue_count": len(validation.issues),
                    "reason_codes": validation.reason_codes,
                    "repair_attempt": repair_attempt,
                    "semantic_supported_count": sum(
                        item.status is SemanticSupportStatus.SUPPORTED for item in semantic
                    ),
                    "semantic_unsupported_count": sum(
                        item.status is SemanticSupportStatus.UNSUPPORTED for item in semantic
                    ),
                    "semantic_unavailable_count": sum(
                        item.status is SemanticSupportStatus.UNAVAILABLE for item in semantic
                    ),
                },
            )
        )
    return tuple(events)


def task_started_event(
    *,
    task_id: str,
    node: str,
    task_input: object,
    attempt: int,
) -> tuple[AgentExecutionEvent, ...]:
    branch = _task_branch(task_input)
    branch_id = branch.branch_id if branch is not None else None
    events = [
        AgentExecutionEvent(
            event_key=f"node:{task_id}:started",
            event_type="node.status",
            data={
                "step_id": task_id,
                "node": node,
                "branch_id": branch_id,
                "status": "started",
                "attempt": attempt,
                "summary": _started_summary(node),
                "duration_ms": None,
            },
        )
    ]
    if branch is not None and branch.kind != "generate_chart_spec":
        events.append(
            AgentExecutionEvent(
                event_key=f"tool:{task_id}:started",
                event_type="tool.status",
                data={
                    "branch_id": branch.branch_id,
                    "kind": branch.kind,
                    "status": "started",
                    "attempts": 0,
                    "optional": branch.optional,
                    "cache_hit": False,
                    "duration_ms": None,
                    "result": None,
                    "error_code": None,
                },
            )
        )
    return tuple(events)


def task_finished_event(
    *,
    task_id: str,
    node: str,
    task_input: object,
    task_result: object,
    task_error: object,
    attempt: int,
    duration_ms: int,
) -> AgentExecutionEvent:
    branch = _task_branch(task_input)
    trajectory = _task_trajectory(task_result, node)
    status = "failed" if task_error is not None else "completed"
    if trajectory is not None:
        status = trajectory.status.value
    return AgentExecutionEvent(
        event_key=f"node:{task_id}:finished",
        event_type="node.status",
        data={
            "step_id": task_id,
            "node": node,
            "branch_id": branch.branch_id if branch is not None else None,
            "status": status,
            "attempt": attempt,
            "summary": (
                trajectory.summary
                if trajectory is not None
                else (
                    "Execution step failed."
                    if task_error is not None
                    else "Execution step completed."
                )
            ),
            "duration_ms": (
                trajectory.duration_ms
                if trajectory and trajectory.duration_ms is not None
                else duration_ms
            ),
        },
    )


def _branch_summary(branch: ExecutionBranch) -> dict[str, object]:
    common: dict[str, object] = {
        "kind": branch.kind,
        "branch_id": branch.branch_id,
        "depends_on": branch.depends_on,
        "optional": branch.optional,
    }
    if isinstance(branch, DocumentRetrievalBranch):
        return {
            **common,
            "query": branch.request.query,
            "max_attempts": branch.request.max_attempts,
            "index_name": branch.request.index_name,
            "index_version": branch.request.index_version,
        }
    if isinstance(branch, FinancialFactsBranch):
        request = branch.request
        return {
            **common,
            "company_ids": request.company_ids,
            "tickers": request.tickers,
            "metrics": request.metrics,
            "period_start": request.period_start.isoformat() if request.period_start else None,
            "period_end": request.period_end.isoformat() if request.period_end else None,
            "fiscal_years": request.fiscal_years,
            "fiscal_periods": request.fiscal_periods,
            "units": request.units,
            "limit": request.limit,
        }
    if isinstance(branch, MacroSeriesBranch):
        macro_request = branch.request
        return {
            **common,
            "series_ids": macro_request.series_ids,
            "observation_start": (
                macro_request.observation_start.isoformat()
                if macro_request.observation_start
                else None
            ),
            "observation_end": (
                macro_request.observation_end.isoformat() if macro_request.observation_end else None
            ),
            "include_missing": macro_request.include_missing,
            "limit": macro_request.limit,
        }
    if isinstance(branch, CalculationBranch):
        return {
            **common,
            "operation": branch.operation,
            "input_refs": branch.input_refs,
            "years": str(branch.years) if branch.years is not None else None,
            "window": branch.window,
            "base": str(branch.base),
        }
    chart = branch
    return {
        **common,
        "chart_type": chart.chart_type,
        "dataset_ref": chart.dataset_ref,
        "title": chart.title,
        "x_label": chart.x_label,
    }


def _tool_outcome_event(state: AgentState, outcome: BranchOutcome) -> AgentExecutionEvent:
    duration = next(
        (
            item.duration_ms
            for item in reversed(state.get("trajectory", ()))
            if item.details.get("branch_id") == outcome.branch_id
        ),
        None,
    )
    return AgentExecutionEvent(
        event_key=f"tool:{outcome.branch_id}:{outcome.status.value}:{outcome.attempts}",
        event_type="tool.status",
        data={
            "branch_id": outcome.branch_id,
            "kind": outcome.kind,
            "status": outcome.status.value,
            "attempts": outcome.attempts,
            "optional": outcome.optional,
            "cache_hit": outcome.attempts == 0,
            "duration_ms": duration,
            "result": _result_summary(state, outcome),
            "error_code": outcome.error.code if outcome.error is not None else None,
        },
    )


def _result_summary(state: AgentState, outcome: BranchOutcome) -> dict[str, object] | None:
    if outcome.status.value != "completed":
        return None
    if outcome.kind == "retrieve_documents":
        retrieval_item = next(
            (
                value
                for value in state.get("retrieval_results", ())
                if value.branch_id == outcome.branch_id
            ),
            None,
        )
        if retrieval_item is None:
            return None
        trace = retrieval_item.result.trace
        return {
            "kind": outcome.kind,
            "strategy": retrieval_item.result.plan.strategy,
            "evidence_count": len(retrieval_item.result.context),
            "context_tokens": trace.final_context_tokens,
            "attempts": tuple(
                {
                    "attempt": attempt.attempt,
                    "strategy": attempt.strategy,
                    "action": attempt.action,
                    "reason": attempt.reason,
                    "evidence_count": attempt.evidence_count,
                    "context_tokens": attempt.context_tokens,
                }
                for attempt in trace.attempts
            ),
            "abstained": trace.abstained,
            "abstention_reason": trace.abstention_reason,
        }
    if outcome.kind == "query_financial_facts":
        financial_item = next(
            (
                value
                for value in state.get("financial_results", ())
                if value.branch_id == outcome.branch_id
            ),
            None,
        )
        if financial_item is None:
            return None
        return {
            "kind": outcome.kind,
            "observation_count": len(financial_item.result.observations),
            "metrics": financial_item.result.query.metrics,
            "available_units": financial_item.result.available_units,
            "warning_count": len(financial_item.result.warnings),
            "warnings": _safe_warnings(financial_item.result.warnings),
        }
    if outcome.kind == "query_macro_series":
        macro_item = next(
            (
                value
                for value in state.get("macro_results", ())
                if value.branch_id == outcome.branch_id
            ),
            None,
        )
        if macro_item is None:
            return None
        return {
            "kind": outcome.kind,
            "series_count": len(macro_item.result.series),
            "observation_count": len(macro_item.result.observations),
            "series_ids": macro_item.result.query.series_ids,
            "warning_count": len(macro_item.result.warnings),
            "warnings": _safe_warnings(macro_item.result.warnings),
        }
    if outcome.kind == "calculate_metrics":
        calculation_item = next(
            (
                value
                for value in state.get("calculations", ())
                if value.branch_id == outcome.branch_id
            ),
            None,
        )
        if calculation_item is None:
            return None
        return {
            "kind": outcome.kind,
            "operation": calculation_item.result.operation,
            "formula": calculation_item.result.formula,
            "unit": calculation_item.result.unit,
            "output_count": len(calculation_item.result.values),
            "source_count": len(calculation_item.result.sources),
            "warning_count": len(calculation_item.result.warnings),
            "warnings": _safe_warnings(calculation_item.result.warnings),
        }
    return None


def _task_branch(task_input: object) -> ExecutionBranch | None:
    if not isinstance(task_input, dict):
        return None
    branch = task_input.get("active_branch")
    branch_types = (
        DocumentRetrievalBranch,
        FinancialFactsBranch,
        MacroSeriesBranch,
        CalculationBranch,
        ChartBranch,
    )
    return branch if isinstance(branch, branch_types) else None


def _task_trajectory(task_result: object, node: str) -> TrajectoryEvent | None:
    if not isinstance(task_result, dict):
        return None
    trajectory = task_result.get("trajectory", ())
    if not isinstance(trajectory, (tuple, list)):
        return None
    return next(
        (
            value
            for value in reversed(trajectory)
            if isinstance(value, TrajectoryEvent) and value.node == node
        ),
        None,
    )


def _safe_warnings(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value[:_MAX_WARNING_CHARS] for value in values[:_MAX_WARNINGS])


def _started_summary(node: str) -> str:
    return {
        "parse_question": "Classifying the research question.",
        "resolve_entities": "Resolving companies, metrics, and reporting periods.",
        "prepare_company_data": "Downloading report...",
        "plan_request": "Building a bounded execution plan.",
        "hydrate_cached_results": "Checking reusable session results.",
        "retrieve_documents": "Retrieving documentary evidence.",
        "query_financial_facts": "Querying structured financial facts.",
        "query_macro_series": "Querying macroeconomic observations.",
        "evaluate_context": "Evaluating evidence coverage.",
        "calculate_metrics": "Running a deterministic calculation.",
        "generate_chart_spec": "Building a validated chart specification.",
        "merge_evidence": "Merging evidence and source lineage.",
        "generate_answer": "Generating a grounded draft answer.",
        "validate_citations": "Validating claims and citations.",
        "repair_or_abstain": "Repairing unsupported claims or preparing abstention.",
        "finalize_response": "Finalizing the validated research response.",
        "start_turn": "Preparing the research session.",
    }.get(node, "Executing a research workflow step.")


def _stable_key(prefix: str, value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    return f"{prefix}:{digest}"
