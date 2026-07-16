from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from company_lens.agent.calculation_intents import CalculationOperation
from company_lens.agent.schemas import (
    CalculationBranch,
    ExecutionPlan,
    FinancialFactsBranch,
    MacroSeriesBranch,
    QuestionAnalysis,
    SessionMemory,
)

_REASON_ORDER = ("operation", "metrics", "parameters", "inheritance", "missing", "ambiguous")


class EffectiveCalculationIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: CalculationOperation
    metrics: tuple[str, ...] = ()
    window: int | None = None
    years: Decimal | None = None
    base: Decimal | None = None
    source: Literal["current", "inherited"]


class OperationConflict(BaseModel):
    model_config = ConfigDict(frozen=True)

    required: bool
    reason_codes: tuple[str, ...] = ()
    branch_ids: tuple[str, ...] = ()


def _effective_calculation_intents(
    analysis: QuestionAnalysis,
    memory: SessionMemory | None,
) -> tuple[EffectiveCalculationIntent, ...]:
    if analysis.calculation_intents:
        return tuple(
            EffectiveCalculationIntent(
                operation=intent.operation,
                metrics=intent.metrics,
                window=intent.window,
                years=intent.years,
                base=intent.base,
                source="current",
            )
            for intent in analysis.calculation_intents
        )
    if not analysis.inherit_previous_calculation_intents:
        return ()
    previous = memory.last_execution_plan if memory is not None else None
    if previous is None:
        return ()
    return _intents_from_final_plan(previous)


def _detect_operation_conflict(
    analysis: QuestionAnalysis,
    plan: ExecutionPlan,
    memory: SessionMemory | None,
) -> OperationConflict:
    branches = tuple(branch for branch in plan.branches if isinstance(branch, CalculationBranch))
    intents = _effective_calculation_intents(analysis, memory)
    reasons: set[str] = set()
    conflicting_ids: set[str] = set()

    if (
        analysis.inherit_previous_calculation_intents
        and not analysis.calculation_intents
        and not intents
    ):
        reasons.add("inheritance")
    if branches and not intents:
        reasons.add("missing")
        conflicting_ids.update(branch.branch_id for branch in branches)
    if intents and not branches:
        reasons.add("missing")

    represented: set[int] = set()
    for branch in branches:
        branch_metrics = _branch_metrics(plan, branch)
        candidates = tuple(
            (index, intent)
            for index, intent in enumerate(intents)
            if _metrics_compatible(intent.metrics, branch_metrics)
        )
        if not candidates:
            reasons.add("metrics" if intents else "missing")
            conflicting_ids.add(branch.branch_id)
            continue
        if len(candidates) > 1:
            reasons.add("ambiguous")
            conflicting_ids.add(branch.branch_id)
            continue
        index, intent = candidates[0]
        represented.add(index)
        if branch.operation != intent.operation:
            reasons.add("operation")
            conflicting_ids.add(branch.branch_id)
        if not _scalar_parameters_compatible(intent, branch):
            reasons.add("parameters")
            conflicting_ids.add(branch.branch_id)

    if intents and len(represented) != len(intents):
        unmatched = tuple(index for index in range(len(intents)) if index not in represented)
        if unmatched and not reasons.intersection({"metrics", "ambiguous", "missing"}):
            reasons.add("metrics")

    ordered_reasons = tuple(reason for reason in _REASON_ORDER if reason in reasons)
    ordered_branch_ids = tuple(
        branch.branch_id for branch in branches if branch.branch_id in conflicting_ids
    )
    return OperationConflict(
        required=bool(ordered_reasons),
        reason_codes=ordered_reasons,
        branch_ids=ordered_branch_ids,
    )


def _intents_from_final_plan(plan: ExecutionPlan) -> tuple[EffectiveCalculationIntent, ...]:
    intents: list[EffectiveCalculationIntent] = []
    seen: set[tuple[object, ...]] = set()
    for branch in plan.branches:
        if not isinstance(branch, CalculationBranch):
            continue
        intent = EffectiveCalculationIntent(
            operation=branch.operation,
            metrics=_branch_metrics(plan, branch),
            window=branch.window if branch.operation == "rolling_average" else None,
            years=branch.years if branch.operation == "cagr" else None,
            base=branch.base if branch.operation == "normalised_index" else None,
            source="inherited",
        )
        signature = (
            intent.operation,
            tuple(_normalized_metric(value) for value in intent.metrics),
            intent.window,
            intent.years,
            intent.base,
        )
        if signature in seen:
            continue
        seen.add(signature)
        intents.append(intent)
    return tuple(intents)


def _branch_metrics(plan: ExecutionPlan, branch: CalculationBranch) -> tuple[str, ...]:
    by_id = {item.branch_id: item for item in plan.branches}
    metrics: list[str] = []
    for reference in branch.input_refs:
        source = by_id.get(reference)
        if isinstance(source, FinancialFactsBranch):
            metrics.extend(source.request.metrics)
        elif isinstance(source, MacroSeriesBranch):
            metrics.extend(source.request.series_ids)
    return tuple(metrics)


def _metrics_compatible(intent: tuple[str, ...], branch: tuple[str, ...]) -> bool:
    if not intent:
        return True
    return tuple(_normalized_metric(value) for value in intent) == tuple(
        _normalized_metric(value) for value in branch
    )


def _normalized_metric(value: str) -> str:
    return " ".join(value.split()).casefold()


def _scalar_parameters_compatible(
    intent: EffectiveCalculationIntent,
    branch: CalculationBranch,
) -> bool:
    if intent.operation == "rolling_average":
        return intent.window == branch.window
    if intent.operation == "cagr":
        return intent.years == branch.years
    if intent.operation == "normalised_index" and intent.base is not None:
        return intent.base == branch.base
    return True


__all__ = (
    "EffectiveCalculationIntent",
    "OperationConflict",
    "_branch_metrics",
    "_detect_operation_conflict",
    "_effective_calculation_intents",
)
