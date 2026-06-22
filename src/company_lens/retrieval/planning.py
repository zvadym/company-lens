from __future__ import annotations

import re

from company_lens.retrieval.adaptive_schemas import (
    EvidenceScope,
    ResolvedQuery,
    RetrievalBudget,
    RetrievalPlan,
    RetrievalStrategy,
)
from company_lens.retrieval.schemas import RetrievalFilters

COMPARATIVE_MARKERS = (
    "compare",
    "comparison",
    "versus",
    " vs ",
    "difference",
    "trend",
    "порівняй",
    "порівнян",
    "проти",
    "динамік",
)
SUMMARY_MARKERS = ("summary", "overview", "high level", "коротко", "огляд", "підсум")
EXPLANATORY_MARKERS = ("why", "explain", "reason", "ризик", "чому", "поясни")
NO_EVIDENCE_PATTERNS = (
    re.compile(r"^(hello|hi|thanks|thank you)[.!? ]*$", re.IGNORECASE),
    re.compile(r"^(привіт|дякую)[.!? ]*$", re.IGNORECASE),
)


class RetrievalPlanner:
    def plan(
        self,
        resolved: ResolvedQuery,
        *,
        max_attempts: int = 3,
        evidence_scope: EvidenceScope = "auto",
    ) -> RetrievalPlan:
        query_folded = resolved.query.casefold()
        rationale: list[str] = []
        comparative = (
            len(resolved.company_ids) > 1
            or len(resolved.fiscal_years) > 1
            or any(marker in query_folded for marker in COMPARATIVE_MARKERS)
        )

        unresolved_exact = any(
            entity.status == "unresolved" and entity.kind in {"filing", "company"}
            for entity in resolved.entities
        )
        strategy: RetrievalStrategy
        if resolved.has_ambiguity:
            strategy = "none"
            rationale.append("ambiguous_entity_requires_clarification")
        elif unresolved_exact:
            strategy = "none"
            rationale.append("exact_identifier_not_found")
        elif any(pattern.match(resolved.query) for pattern in NO_EVIDENCE_PATTERNS):
            strategy = "none"
            rationale.append("question_does_not_require_evidence")
        elif evidence_scope == "documents":
            strategy = "detailed"
            rationale.append("document_evidence_required")
        elif resolved.metrics and any(marker in query_folded for marker in EXPLANATORY_MARKERS):
            strategy = "hybrid"
            rationale.append("metric_requires_structured_and_narrative_evidence")
        elif resolved.metrics:
            strategy = "structured_only"
            rationale.append("known_metric_prefers_structured_facts")
        elif any(marker in query_folded for marker in SUMMARY_MARKERS):
            strategy = "summary_only"
            rationale.append("high_level_intent_prefers_summaries")
        elif comparative:
            strategy = "detailed"
            rationale.append("comparative_intent_requires_source_chunks")
        elif _section_codes(query_folded):
            strategy = "section_level"
            rationale.append("known_section_intent")
        else:
            strategy = "detailed"
            rationale.append("default_evidence_strategy")

        budget = _budget(comparative=comparative, strategy=strategy)
        dates = resolved.dates
        filters = RetrievalFilters(
            company_ids=resolved.company_ids,
            accession_numbers=resolved.accession_numbers,
            filing_forms=resolved.filing_forms,
            period_end_from=min(dates) if dates else None,
            period_end_to=max(dates) if dates else None,
            fiscal_years=resolved.fiscal_years,
            fiscal_periods=resolved.fiscal_periods,
            section_codes=_section_codes(query_folded),
        )
        return RetrievalPlan(
            query=resolved.query,
            strategy=strategy,
            filters=filters,
            budget=budget,
            metrics=resolved.metrics,
            comparative=comparative,
            max_attempts=max_attempts,
            rationale=tuple(rationale),
            evidence_scope=evidence_scope,
        )


def _budget(*, comparative: bool, strategy: RetrievalStrategy) -> RetrievalBudget:
    if strategy == "none":
        return RetrievalBudget(
            max_documents=1,
            max_sections=1,
            max_chunks=1,
            max_tokens=100,
            max_per_company=1,
            max_per_period=1,
        )
    if strategy == "structured_only":
        return RetrievalBudget(
            max_documents=2,
            max_sections=2,
            max_chunks=4,
            max_tokens=800,
            max_per_company=4,
            max_per_period=2,
        )
    if strategy == "summary_only":
        return RetrievalBudget(
            max_documents=3,
            max_sections=5,
            max_chunks=2,
            max_tokens=1_500,
            max_per_company=3,
            max_per_period=2,
        )
    if comparative:
        return RetrievalBudget(
            max_documents=8,
            max_sections=16,
            max_chunks=24,
            max_tokens=8_000,
            max_per_company=12,
            max_per_period=8,
        )
    return RetrievalBudget()


def _section_codes(query: str) -> tuple[str, ...]:
    mappings = {
        "risk_factors": ("risk", "risks", "ризик"),
        "business": ("business", "бізнес"),
        "management_discussion": ("md&a", "management discussion", "керівництв"),
    }
    return tuple(
        code for code, markers in mappings.items() if any(marker in query for marker in markers)
    )
