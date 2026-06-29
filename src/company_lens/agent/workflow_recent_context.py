from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _recent_company_context(memory: SessionMemory) -> ResolvedQuery:
    queries = memory.recent_resolved_queries or (memory.last_resolved_query,)
    queries = tuple(query for query in queries if query is not None)
    if not queries:
        return _recent_artifact_resolved_context(memory)
    base = queries[-1]
    company_entities = []
    seen_entities: set[tuple[str, str]] = set()
    company_ids: list[uuid.UUID] = []
    seen_company_ids: set[uuid.UUID] = set()
    for query in queries:
        for company_id in query.company_ids:
            if company_id not in seen_company_ids:
                seen_company_ids.add(company_id)
                company_ids.append(company_id)
        for entity in query.entities:
            if entity.kind not in {"company", "public_company"}:
                continue
            key = (entity.kind, entity.canonical_value or entity.mention.casefold())
            if key in seen_entities:
                continue
            seen_entities.add(key)
            company_entities.append(entity)
    for company_id in _cached_financial_company_ids(memory):
        if company_id not in seen_company_ids:
            seen_company_ids.add(company_id)
            company_ids.append(company_id)
    for company_id in _artifact_company_ids(memory):
        if company_id not in seen_company_ids:
            seen_company_ids.add(company_id)
            company_ids.append(company_id)
    non_company_entities = tuple(
        entity for entity in base.entities if entity.kind not in {"company", "public_company"}
    )
    return base.model_copy(
        update={
            "entities": (*company_entities, *non_company_entities),
            "company_ids": tuple(company_ids),
        }
    )


def _recent_artifact_resolved_context(memory: SessionMemory) -> ResolvedQuery:
    artifact = _selected_chart_artifact(memory)
    if artifact is None:
        return ResolvedQuery(query="recent artifacts")
    return ResolvedQuery(
        query=artifact.user_question or "recent chart artifact",
        company_ids=artifact.company_ids,
        metrics=artifact.metrics,
    )


def _recent_company_ids(memory: SessionMemory) -> tuple[uuid.UUID, ...]:
    seen: set[uuid.UUID] = set()
    company_ids: list[uuid.UUID] = []
    queries = memory.recent_resolved_queries
    if memory.last_resolved_query is not None and memory.last_resolved_query not in queries:
        queries = (*queries, memory.last_resolved_query)
    for query in queries:
        for company_id in query.company_ids:
            if company_id in seen:
                continue
            seen.add(company_id)
            company_ids.append(company_id)
    for company_id in _cached_financial_company_ids(memory):
        if company_id in seen:
            continue
        seen.add(company_id)
        company_ids.append(company_id)
    for company_id in _artifact_company_ids(memory):
        if company_id in seen:
            continue
        seen.add(company_id)
        company_ids.append(company_id)
    return tuple(company_ids)


def _artifact_company_ids(memory: SessionMemory) -> tuple[uuid.UUID, ...]:
    seen: set[uuid.UUID] = set()
    company_ids: list[uuid.UUID] = []
    for artifact in memory.recent_artifacts:
        for company_id in artifact.company_ids:
            if company_id in seen:
                continue
            seen.add(company_id)
            company_ids.append(company_id)
    return tuple(company_ids)


def _cached_financial_company_ids(memory: SessionMemory) -> tuple[uuid.UUID, ...]:
    seen: set[uuid.UUID] = set()
    company_ids: list[uuid.UUID] = []
    for item in memory.cached_source_results:
        result = item.financial_result
        if result is None:
            continue
        for company_id in result.query.company_ids:
            if company_id in seen:
                continue
            seen.add(company_id)
            company_ids.append(company_id)
    return tuple(company_ids)


__all__ = (
    "_recent_company_context",
    "_recent_artifact_resolved_context",
    "_recent_company_ids",
    "_artifact_company_ids",
    "_cached_financial_company_ids",
)  # noqa: E501
