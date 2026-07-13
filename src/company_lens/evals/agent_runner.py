from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from typing import Protocol

from company_lens.agent.events import AgentExecutionEvent
from company_lens.agent.schemas import AgentState, ExecutionPolicy
from company_lens.evals.golden import GoldenDataset, GoldenDatasetCase
from company_lens.evals.models import (
    CaseObservation,
    ObservedGoldenResults,
    ObservedNodeAttempt,
    ObservedNodeLatency,
    ObservedOperationalMetrics,
)
from company_lens.evals.observation import (
    case_observation_from_state,
    infrastructure_case_observation,
    observed_result_from_observation,
    observed_result_from_state,
)
from company_lens.observability.telemetry import ModelUsageRecord, collect_model_usage


class GoldenResearchAgent(Protocol):
    def run(
        self,
        question: str,
        *,
        session_id: str,
        policy: ExecutionPolicy,
        observer: Callable[[AgentExecutionEvent], None] | None = None,
    ) -> AgentState: ...


def run_golden_agent_observations(
    dataset: GoldenDataset,
    agent: GoldenResearchAgent,
    *,
    policy: ExecutionPolicy,
    max_cases: int | None = None,
    case_ids: tuple[str, ...] = (),
    session_prefix: str = "golden-eval",
    run_token: str | None = None,
) -> tuple[CaseObservation, ...]:
    cases = select_golden_cases(dataset, case_ids=case_ids, max_cases=max_cases)
    token = run_token or uuid.uuid4().hex[:12]
    return tuple(
        _run_case(
            case,
            agent,
            policy=policy,
            session_id=_case_session_id(session_prefix, token, case.id),
        )
        for case in cases
    )


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
    observations = run_golden_agent_observations(
        dataset,
        agent,
        policy=policy,
        max_cases=max_cases,
        case_ids=case_ids,
        session_prefix=session_prefix,
        run_token=run_token,
    )
    failed = [item.case_id for item in observations if item.outcome == "infrastructure_error"]
    if failed:
        raise ValueError(f"golden case execution failed: {', '.join(failed)}")
    return ObservedGoldenResults(
        schema_version=1,
        dataset_name=dataset.name,
        dataset_version=dataset.version,
        results=tuple(observed_result_from_observation(item) for item in observations),
    )


def select_golden_cases(
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
) -> CaseObservation:
    user_turns = [turn for turn in case.conversation if turn.role == "user"]
    if len(user_turns) != len(case.conversation) or not user_turns:
        return infrastructure_case_observation(case, failure_code="invalid_case_conversation")

    state: AgentState | None = None
    started = time.perf_counter()
    first_event_ms: int | None = None

    def observe(_: AgentExecutionEvent) -> None:
        nonlocal first_event_ms
        if first_event_ms is None:
            first_event_ms = _elapsed_ms(started)

    try:
        with collect_model_usage() as model_usage:
            for turn in user_turns:
                state = agent.run(
                    turn.content,
                    session_id=session_id,
                    policy=policy,
                    observer=observe,
                )
    except Exception:
        return infrastructure_case_observation(
            case,
            failure_code="agent_execution_failed",
        )
    if state is None:
        return infrastructure_case_observation(case, failure_code="agent_state_unavailable")
    return case_observation_from_state(
        case,
        state,
        operational=_operational_metrics(
            state,
            policy=policy,
            total_latency_ms=_elapsed_ms(started),
            time_to_first_event_ms=first_event_ms,
            model_usage=tuple(model_usage),
        ),
    )


def _operational_metrics(
    state: AgentState,
    *,
    policy: ExecutionPolicy,
    total_latency_ms: int,
    time_to_first_event_ms: int | None,
    model_usage: tuple[ModelUsageRecord, ...] = (),
) -> ObservedOperationalMetrics:
    node_attempts = tuple(
        ObservedNodeAttempt(node=_node_name(item.node), attempts=item.attempts)
        for item in state.get("node_attempts", ())
    )
    input_tokens, output_tokens, total_tokens, cost_usd = _model_usage_totals(model_usage)
    tool_calls_used = state.get("tool_calls_used", 0)
    return ObservedOperationalMetrics(
        total_latency_ms=total_latency_ms,
        time_to_first_event_ms=time_to_first_event_ms,
        node_latencies=tuple(
            ObservedNodeLatency(node=event.node, duration_ms=event.duration_ms)
            for event in state.get("trajectory", ())
            if event.duration_ms is not None
        ),
        tool_calls_used=tool_calls_used,
        repair_attempts=state.get("repair_attempts", 0),
        api_calls=len(model_usage) if model_usage else tool_calls_used,
        retry_count=sum(max(0, item.attempts - 1) for item in node_attempts),
        node_attempts=node_attempts,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        policy_max_tool_calls=policy.max_tool_calls,
        policy_max_repair_attempts=policy.max_repair_attempts,
        policy_max_retries_per_node=policy.max_retries_per_node,
    )


def _model_usage_totals(
    records: tuple[ModelUsageRecord, ...],
) -> tuple[int | None, int | None, int | None, float | None]:
    if not records:
        return None, None, None, None
    costs = [record.cost_usd for record in records if record.cost_usd is not None]
    return (
        sum(record.input_tokens for record in records),
        sum(record.output_tokens for record in records),
        sum(record.total_tokens for record in records),
        round(sum(costs), 10) if costs else None,
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _node_name(value: str) -> str:
    return value.split(":", 1)[0]


def _case_session_id(prefix: str, run_token: str, case_id: str) -> str:
    safe_prefix = _safe_session_part(prefix) or "golden-eval"
    safe_token = _safe_session_part(run_token) or uuid.uuid4().hex[:12]
    safe_case = _safe_session_part(case_id)
    session_id = f"{safe_prefix}-{safe_token}-{safe_case}"
    return session_id[:128].rstrip(".:-_") or f"golden-eval-{uuid.uuid4().hex[:12]}"


def _safe_session_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._:-]+", "-", value.strip()).strip(".:-_")


__all__ = [
    "GoldenResearchAgent",
    "observed_result_from_state",
    "run_golden_agent_dataset",
    "run_golden_agent_observations",
    "select_golden_cases",
]
