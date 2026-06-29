from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _merge_follow_up_resolution(
    current: ResolvedQuery,
    previous: ResolvedQuery,
    *,
    include_previous_companies: bool = False,
) -> ResolvedQuery:
    current_has_company = _has_company_like_entity(current)
    current_kinds = {entity.kind for entity in current.entities}
    inherited_company_entities = (
        ()
        if current_has_company and not include_previous_companies
        else tuple(
            entity for entity in previous.entities if entity.kind in {"company", "public_company"}
        )
    )
    inherited_entities = tuple(
        entity
        for entity in previous.entities
        if entity.kind not in current_kinds and entity.kind not in {"company", "public_company"}
    )
    company_ids = (
        _merged_company_ids(previous.company_ids, current.company_ids)
        if include_previous_companies
        else current.company_ids or (() if current_has_company else previous.company_ids)
    )
    return current.model_copy(
        update={
            "entities": (*current.entities, *inherited_company_entities, *inherited_entities),
            "company_ids": company_ids,
            "accession_numbers": current.accession_numbers or previous.accession_numbers,
            "filing_forms": current.filing_forms or previous.filing_forms,
            "fiscal_years": current.fiscal_years or previous.fiscal_years,
            "fiscal_periods": current.fiscal_periods or previous.fiscal_periods,
            "dates": current.dates or previous.dates,
            "metrics": current.metrics or previous.metrics,
        }
    )


def _merge_follow_up_if_needed(
    resolved: ResolvedQuery,
    analysis: QuestionAnalysis | None,
    memory: SessionMemory | None,
) -> ResolvedQuery:
    if (
        analysis is not None
        and analysis.is_follow_up
        and memory is not None
        and (memory.last_resolved_query is not None or memory.recent_artifacts)
    ):
        previous = (
            _recent_company_context(memory)
            if _should_inherit_recent_companies(resolved, analysis, memory)
            else memory.last_resolved_query
        )
        if previous is None:
            return resolved
        return _merge_follow_up_resolution(
            resolved,
            previous,
            include_previous_companies=_should_add_to_existing_company_set(
                resolved,
                analysis,
                memory,
            ),
        )
    return resolved


def _merged_company_ids(
    previous: tuple[uuid.UUID, ...],
    current: tuple[uuid.UUID, ...],
) -> tuple[uuid.UUID, ...]:
    return tuple(dict.fromkeys((*previous, *current)))


def _has_company_like_entity(resolved: ResolvedQuery) -> bool:
    return any(entity.kind in {"company", "public_company"} for entity in resolved.entities)


def _updated_recent_resolved_queries(
    previous: tuple[ResolvedQuery, ...],
    current: ResolvedQuery | None,
    *,
    limit: int = 5,
) -> tuple[ResolvedQuery, ...]:
    if current is None:
        return previous[-limit:]
    if previous and previous[-1] == current:
        return previous[-limit:]
    return (*previous, current)[-limit:]


def _should_inherit_recent_companies(
    resolved: ResolvedQuery,
    analysis: QuestionAnalysis,
    memory: SessionMemory,
) -> bool:
    if _has_company_like_entity(resolved):
        return _should_add_to_existing_company_set(resolved, analysis, memory)
    recent_company_count = len(_recent_company_ids(memory))
    if _requests_period_override(analysis.normalized_question, analysis):
        return recent_company_count >= 1
    if _requests_plan_replay(analysis.normalized_question, analysis):
        return recent_company_count >= 1
    if recent_company_count < 2:
        return False
    return _references_multiple_prior_companies(analysis.normalized_question) or (
        analysis.chart_requested and _analysis_requests_comparison(analysis)
    )


def _should_add_to_existing_company_set(
    resolved: ResolvedQuery,
    analysis: QuestionAnalysis,
    memory: SessionMemory,
) -> bool:
    if not _has_company_like_entity(resolved):
        return False
    if not _recent_company_ids(memory):
        return False
    return _analysis_requests_add_series(analysis) or _question_requests_add_series(
        analysis.normalized_question
    )


def _references_multiple_prior_companies(question: str) -> bool:
    normalized = question.casefold()
    markers = (
        "these companies",
        "those companies",
        "both companies",
        "the companies",
        "these two",
        "ці компан",
        "цих компан",
        "обидві компан",
        "обидва компан",
        "эти компан",
        "обе компан",
    )
    return any(marker in normalized for marker in markers)


def _analysis_requests_comparison(analysis: QuestionAnalysis) -> bool:
    return any(
        marker in reason
        for reason in analysis.reason_codes
        for marker in ("comparison", "compare", "cross_company")
    )


def _analysis_requests_add_series(analysis: QuestionAnalysis) -> bool:
    return any(
        marker in reason
        for reason in analysis.reason_codes
        for marker in ("add_series", "add_to_chart", "add_company", "adds_company")
    )


def _question_requests_add_series(question: str) -> bool:
    normalized = question.casefold()
    markers = (
        "add ",
        "add to",
        "include ",
        "also add",
        "додай",
        "добав",
        "добавь",
    )
    return any(marker in normalized for marker in markers)


__all__ = (
    "_merge_follow_up_resolution",
    "_merge_follow_up_if_needed",
    "_merged_company_ids",
    "_has_company_like_entity",
    "_updated_recent_resolved_queries",
    "_should_inherit_recent_companies",
    "_should_add_to_existing_company_set",
    "_references_multiple_prior_companies",
    "_analysis_requests_comparison",
    "_analysis_requests_add_series",
    "_question_requests_add_series",
)  # noqa: E501
