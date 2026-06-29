from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _should_extract_company_mentions(
    analysis: QuestionAnalysis | None,
) -> bool:
    if analysis is None or analysis.route is ResearchRoute.UNSUPPORTED:
        return False
    capabilities = set(analysis.required_capabilities)
    return (
        analysis.chart_requested
        or AgentCapability.FINANCIAL_FACTS in capabilities
        or AgentCapability.DOCUMENTS in capabilities
    )


def _resolved_query_with_extra_entities(
    resolved: ResolvedQuery,
    entities: tuple[EntityResolution, ...],
) -> ResolvedQuery:
    seen = {(entity.kind, entity.mention.casefold()) for entity in resolved.entities}
    additions = tuple(
        entity for entity in entities if (entity.kind, entity.mention.casefold()) not in seen
    )
    if not additions:
        return resolved
    company_ids = tuple(
        dict.fromkeys(
            (
                *resolved.company_ids,
                *(
                    company_id
                    for entity in additions
                    if (company_id := _entity_company_id(entity)) is not None
                ),
            )
        )
    )
    return resolved.model_copy(
        update={
            "entities": (*resolved.entities, *additions),
            "company_ids": company_ids,
        }
    )


def _resolved_query_without_company_entities(resolved: ResolvedQuery) -> ResolvedQuery:
    has_company_entities = _has_company_like_entity(resolved)
    return resolved.model_copy(
        update={
            "entities": tuple(
                entity
                for entity in resolved.entities
                if entity.kind not in {"company", "public_company"}
            ),
            "company_ids": () if has_company_entities else resolved.company_ids,
        }
    )


__all__ = (
    "_should_extract_company_mentions",
    "_resolved_query_with_extra_entities",
    "_resolved_query_without_company_entities",
)
