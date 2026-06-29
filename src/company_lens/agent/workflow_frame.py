from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _resolve_question_entities(
    question: str,
    analysis: QuestionAnalysis | None,
    tools: ResearchTools,
) -> ResolvedQuery:
    if _should_extract_company_mentions(analysis):
        return tools.resolve_non_company_entities(question)
    return tools.resolve_entities(question)


def _build_research_frame(
    *,
    question: str,
    analysis: QuestionAnalysis | None,
    resolved: ResolvedQuery,
    memory: SessionMemory | None,
) -> ResearchFrame | None:
    if analysis is None:
        return None
    return ResearchFrame(
        question=question,
        analysis=analysis,
        resolved_query=resolved,
        company_targets=_company_targets_from_resolved(
            resolved,
            source=_company_target_source(analysis, resolved, memory),
        ),
        inherited_from_previous=_inherited_previous_company_target(analysis, resolved, memory),
        follow_up_operation=_previous_growth_operation(memory) if analysis.is_follow_up else None,
        follow_up_window=_previous_calculation_window(memory) if analysis.is_follow_up else None,
    )


def _ensure_research_frame(
    state: AgentState,
    *,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    memory: SessionMemory | None,
) -> ResearchFrame:
    frame = state.get("research_frame")
    if frame is not None and frame.analysis == analysis and frame.resolved_query == resolved:
        return frame
    built = _build_research_frame(
        question=state["question"],
        analysis=analysis,
        resolved=resolved,
        memory=memory,
    )
    assert built is not None
    return built


def _company_targets_from_resolved(
    resolved: ResolvedQuery,
    *,
    source: CompanyTargetSource,
) -> tuple[CompanyTarget, ...]:
    targets: list[CompanyTarget] = []
    seen_company_ids: set[uuid.UUID] = set()
    seen_mentions: set[tuple[str, str]] = set()
    for entity in resolved.entities:
        if entity.kind not in {"company", "public_company"}:
            continue
        company_id = _entity_company_id(entity)
        ticker = _entity_public_ticker(entity)
        display_name = entity.candidates[0].display_value if entity.candidates else None
        if company_id is not None:
            seen_company_ids.add(company_id)
        key = (entity.kind, entity.canonical_value or entity.mention.casefold())
        if key in seen_mentions:
            continue
        seen_mentions.add(key)
        targets.append(
            CompanyTarget(
                mention=entity.mention,
                company_id=company_id,
                ticker=ticker,
                display_name=display_name,
                status=entity.status,
                source=source,
            )
        )
    for company_id in resolved.company_ids:
        if company_id in seen_company_ids:
            continue
        targets.append(
            CompanyTarget(
                mention=str(company_id),
                company_id=company_id,
                status="resolved",
                source=source,
            )
        )
    return tuple(targets)


def _entity_company_id(entity: EntityResolution) -> uuid.UUID | None:
    if entity.canonical_value is not None:
        parsed = _uuid_or_none(entity.canonical_value)
        if parsed is not None:
            return parsed
    for candidate in entity.candidates:
        if candidate.id is not None:
            return candidate.id
        parsed = _uuid_or_none(candidate.canonical_value)
        if parsed is not None:
            return parsed
    return None


def _entity_public_ticker(entity: EntityResolution) -> str | None:
    if entity.kind != "public_company" or not entity.candidates:
        return None
    value = entity.candidates[0].canonical_value.strip().upper()
    return None if _uuid_or_none(value) is not None else value


def _uuid_or_none(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _company_target_source(
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    memory: SessionMemory | None,
) -> CompanyTargetSource:
    if _inherited_previous_company_target(analysis, resolved, memory):
        return "follow_up_context"
    return "current_question"


def _inherited_previous_company_target(
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    memory: SessionMemory | None,
) -> bool:
    if not analysis.is_follow_up or memory is None or memory.last_resolved_query is None:
        return False
    previous_ids = set(memory.last_resolved_query.company_ids)
    return bool(resolved.company_ids and set(resolved.company_ids).issubset(previous_ids))


__all__ = (
    "_resolve_question_entities",
    "_build_research_frame",
    "_ensure_research_frame",
    "_company_targets_from_resolved",
    "_entity_company_id",
    "_entity_public_ticker",
    "_uuid_or_none",
    "_company_target_source",
    "_inherited_previous_company_target",
)  # noqa: E501
