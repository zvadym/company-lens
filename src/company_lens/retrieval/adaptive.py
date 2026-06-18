from __future__ import annotations

import math
import re
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from company_lens.db.models import (
    Company,
    DocumentSummary,
    DocumentVersion,
    FilingSection,
    FinancialFact,
    SectionSummary,
    SourceDocument,
)
from company_lens.retrieval.adaptive_schemas import (
    AdaptiveRetrievalRequest,
    AdaptiveRetrievalResponse,
    ContextEvidence,
    RetrievalAttempt,
    RetrievalBudget,
    RetrievalPlan,
    RetrievalStrategy,
    RetrievalTrace,
)
from company_lens.retrieval.planning import RetrievalPlanner
from company_lens.retrieval.resolution import EntityResolver, metric_aliases
from company_lens.retrieval.schemas import RetrievalFilters, RetrievalRequest
from company_lens.retrieval.service import RetrievalService


class ContextAssembler:
    """Select balanced evidence while keeping citation metadata attached to text."""

    def assemble(
        self,
        evidence: list[ContextEvidence],
        budget: RetrievalBudget,
    ) -> tuple[ContextEvidence, ...]:
        priority = {"document_summary": 0, "section_summary": 1, "financial_fact": 2, "chunk": 3}
        pending = sorted(evidence, key=lambda item: (priority[item.kind], item.citation_label))
        selected: list[ContextEvidence] = []
        company_counts: defaultdict[uuid.UUID | None, int] = defaultdict(int)
        period_counts: defaultdict[str | None, int] = defaultdict(int)
        documents: set[uuid.UUID] = set()
        sections: set[uuid.UUID] = set()
        chunks = 0
        tokens = 0

        while pending:
            pending.sort(
                key=lambda item: (
                    priority[item.kind],
                    company_counts[item.company_id],
                    period_counts[_period_key(item)],
                    item.citation_label,
                )
            )
            item = pending.pop(0)
            if company_counts[item.company_id] >= budget.max_per_company:
                continue
            if period_counts[_period_key(item)] >= budget.max_per_period:
                continue
            if (
                item.document_version_id
                and item.document_version_id not in documents
                and len(documents) >= budget.max_documents
            ):
                continue
            if (
                item.section_id
                and item.section_id not in sections
                and len(sections) >= budget.max_sections
            ):
                continue
            if item.kind == "chunk" and chunks >= budget.max_chunks:
                continue
            remaining = budget.max_tokens - tokens
            if remaining <= 0:
                break
            if item.token_count > remaining:
                item = _truncate_evidence(item, remaining)
            selected.append(item)
            tokens += item.token_count
            company_counts[item.company_id] += 1
            period_counts[_period_key(item)] += 1
            if item.document_version_id:
                documents.add(item.document_version_id)
            if item.section_id:
                sections.add(item.section_id)
            if item.kind == "chunk":
                chunks += 1
        return tuple(selected)


class AdaptiveRetrievalService:
    def __init__(self, *, session: Session) -> None:
        self._session = session
        self._resolver = EntityResolver(session=session)
        self._planner = RetrievalPlanner()
        self._assembler = ContextAssembler()
        self._retrieval = RetrievalService(session=session)

    def retrieve(self, request: AdaptiveRetrievalRequest) -> AdaptiveRetrievalResponse:
        resolved = self._resolver.resolve(request.query)
        plan = self._planner.plan(resolved, max_attempts=request.max_attempts)
        attempts: list[RetrievalAttempt] = []
        final_context: tuple[ContextEvidence, ...] = ()

        for number, strategy in enumerate(_strategy_sequence(plan), start=1):
            candidates, action = self._execute_strategy(
                strategy,
                plan,
                request=request,
                attempt=number,
            )
            context = self._assembler.assemble(candidates, plan.budget)
            sufficient = _is_sufficient(context, plan)
            attempts.append(
                RetrievalAttempt(
                    attempt=number,
                    strategy=strategy,
                    action=action,
                    reason=None if number == 1 else "insufficient_evidence",
                    evidence_count=len(context),
                    context_tokens=sum(item.token_count for item in context),
                )
            )
            final_context = context
            if sufficient:
                break

        abstention_reason: str | None = None
        if plan.strategy == "none":
            if resolved.has_ambiguity:
                abstention_reason = "ambiguous_entity"
            elif any(entity.status == "unresolved" for entity in resolved.entities):
                abstention_reason = "exact_identifier_not_found"
            else:
                abstention_reason = "no_retrieval_required"
        elif not _is_sufficient(final_context, plan):
            abstention_reason = "insufficient_evidence_after_max_attempts"

        trace = RetrievalTrace(
            initial_plan=plan,
            attempts=tuple(attempts),
            final_context_tokens=sum(item.token_count for item in final_context),
            abstained=abstention_reason is not None,
            abstention_reason=abstention_reason,
        )
        return AdaptiveRetrievalResponse(
            query=request.query,
            resolved_query=resolved,
            plan=plan,
            context=final_context,
            trace=trace,
        )

    def _execute_strategy(
        self,
        strategy: RetrievalStrategy,
        plan: RetrievalPlan,
        *,
        request: AdaptiveRetrievalRequest,
        attempt: int,
    ) -> tuple[list[ContextEvidence], str]:
        if strategy == "none":
            return [], "abstain_before_search"
        if strategy == "summary_only":
            return self._document_summaries(plan.filters), "document_summary_lookup"
        if strategy == "section_level":
            return self._section_summaries(plan.filters), "expand_to_section_summaries"
        if strategy == "structured_only":
            return self._financial_facts(plan), "structured_financial_fact_lookup"
        if strategy == "hybrid":
            evidence = self._document_summaries(plan.filters)
            evidence.extend(self._section_summaries(plan.filters))
            evidence.extend(self._financial_facts(plan))
            evidence.extend(
                self._chunks(
                    plan,
                    request=request,
                    top_k=min(plan.budget.max_chunks, 8 + attempt * 4),
                    mode="hybrid",
                )
            )
            return evidence, "combine_structured_and_text_evidence"
        mode = "lexical" if attempt > 1 else "hybrid"
        action = "lexical_fallback" if mode == "lexical" else "detailed_chunk_search"
        evidence = self._document_summaries(plan.filters)
        evidence.extend(self._section_summaries(plan.filters))
        evidence.extend(
            self._chunks(
                plan,
                request=request,
                top_k=min(plan.budget.max_chunks, 8 + attempt * 4),
                mode=mode,
            )
        )
        return evidence, action

    def _document_summaries(self, filters: RetrievalFilters) -> list[ContextEvidence]:
        statement = (
            select(DocumentSummary, DocumentVersion, SourceDocument, Company)
            .join(DocumentVersion, DocumentVersion.id == DocumentSummary.document_version_id)
            .join(SourceDocument, SourceDocument.id == DocumentVersion.document_id)
            .outerjoin(Company, Company.id == SourceDocument.company_id)
        )
        if filters.section_codes:
            statement = statement.join(
                FilingSection,
                FilingSection.document_version_id == DocumentVersion.id,
            ).distinct()
        rows = self._session.execute(_apply_filters(statement, filters)).all()
        return [
            ContextEvidence(
                kind="document_summary",
                content=summary.summary_text,
                citation_label=f"document:{document.stable_source_id}",
                source_url=document.source_url,
                source_id=document.stable_source_id,
                company_id=company.id if company else None,
                company_name=company.display_name if company else None,
                document_version_id=version.id,
                fiscal_year=document.fiscal_year,
                fiscal_period=document.fiscal_period,
                token_count=_token_count(summary.summary_text),
            )
            for summary, version, document, company in rows
        ]

    def _section_summaries(self, filters: RetrievalFilters) -> list[ContextEvidence]:
        statement = (
            select(SectionSummary, FilingSection, DocumentVersion, SourceDocument, Company)
            .join(FilingSection, FilingSection.id == SectionSummary.section_id)
            .join(DocumentVersion, DocumentVersion.id == FilingSection.document_version_id)
            .join(SourceDocument, SourceDocument.id == DocumentVersion.document_id)
            .outerjoin(Company, Company.id == SourceDocument.company_id)
        )
        rows = self._session.execute(_apply_filters(statement, filters)).all()
        return [
            ContextEvidence(
                kind="section_summary",
                content=summary.summary_text,
                citation_label=f"section:{document.stable_source_id}:{section.ordinal_path}",
                source_url=document.source_url,
                source_id=document.stable_source_id,
                company_id=company.id if company else None,
                company_name=company.display_name if company else None,
                document_version_id=version.id,
                section_id=section.id,
                fiscal_year=document.fiscal_year,
                fiscal_period=document.fiscal_period,
                page_start=section.page_start,
                page_end=section.page_end,
                token_count=_token_count(summary.summary_text),
            )
            for summary, section, version, document, company in rows
        ]

    def _financial_facts(self, plan: RetrievalPlan) -> list[ContextEvidence]:
        if not plan.metrics:
            return []
        statement = select(FinancialFact, Company).join(
            Company, Company.id == FinancialFact.company_id
        )
        if plan.filters.company_ids:
            statement = statement.where(FinancialFact.company_id.in_(plan.filters.company_ids))
        if plan.filters.fiscal_years:
            statement = statement.where(FinancialFact.fiscal_year.in_(plan.filters.fiscal_years))
        if plan.filters.fiscal_periods:
            statement = statement.where(
                FinancialFact.fiscal_period.in_(plan.filters.fiscal_periods)
            )
        rows = self._session.execute(statement).all()
        evidence: list[ContextEvidence] = []
        for fact, company in rows:
            searchable = f"{fact.concept} {fact.label or ''}".casefold()
            if not any(
                _metric_matches(searchable, alias)
                for metric in plan.metrics
                for alias in metric_aliases(metric)
            ):
                continue
            value = _decimal_text(fact.value)
            period = fact.fiscal_period or fact.period_end.isoformat()
            content = (
                f"{company.display_name}: {fact.label or fact.concept} = "
                f"{value} {fact.unit} ({period})"
            )
            evidence.append(
                ContextEvidence(
                    kind="financial_fact",
                    content=content,
                    citation_label=f"fact:{fact.id}",
                    source_url=fact.source_url,
                    source_id=fact.accession_number or str(fact.id),
                    company_id=company.id,
                    company_name=company.display_name,
                    document_version_id=fact.document_version_id,
                    financial_fact_id=fact.id,
                    fiscal_year=fact.fiscal_year,
                    fiscal_period=fact.fiscal_period,
                    token_count=_token_count(content),
                )
            )
        return evidence

    def _chunks(
        self,
        plan: RetrievalPlan,
        *,
        request: AdaptiveRetrievalRequest,
        top_k: int,
        mode: str,
    ) -> list[ContextEvidence]:
        response = self._retrieval.retrieve(
            RetrievalRequest(
                query=plan.query,
                mode=mode,  # type: ignore[arg-type]
                filters=plan.filters,
                index_name=request.index_name,
                index_version=request.index_version,
                top_k=max(1, top_k),
                dense_candidate_limit=max(20, top_k * 3),
                lexical_candidate_limit=max(20, top_k * 3),
                max_per_document=plan.budget.max_chunks,
                max_per_period=plan.budget.max_chunks,
            )
        )
        return [
            ContextEvidence(
                kind="chunk",
                content=result.text,
                citation_label=f"chunk:{result.chunk_id}",
                source_url=result.source_url,
                source_id=result.stable_source_id,
                company_id=result.company_id,
                company_name=result.company_display_name,
                document_version_id=result.document_version_id,
                section_id=result.section_id,
                chunk_id=result.chunk_id,
                fiscal_year=result.fiscal_year,
                fiscal_period=result.fiscal_period,
                page_start=result.page_start,
                page_end=result.page_end,
                token_count=_token_count(result.text),
            )
            for result in response.results
        ]


def _strategy_sequence(plan: RetrievalPlan) -> tuple[RetrievalStrategy, ...]:
    sequences: dict[RetrievalStrategy, tuple[RetrievalStrategy, ...]] = {
        "none": ("none",),
        "summary_only": ("summary_only", "section_level", "detailed"),
        "section_level": ("section_level", "detailed", "hybrid"),
        "detailed": ("detailed", "section_level", "hybrid"),
        "structured_only": ("structured_only", "hybrid", "detailed"),
        "hybrid": ("hybrid", "structured_only", "detailed"),
    }
    return sequences[plan.strategy][: plan.max_attempts]


def _apply_filters(statement: Select[Any], filters: RetrievalFilters) -> Select[Any]:
    if filters.company_ids:
        statement = statement.where(SourceDocument.company_id.in_(filters.company_ids))
    if filters.document_version_ids:
        statement = statement.where(DocumentVersion.id.in_(filters.document_version_ids))
    if filters.accession_numbers:
        statement = statement.where(SourceDocument.accession_number.in_(filters.accession_numbers))
    if filters.document_kinds:
        statement = statement.where(SourceDocument.kind.in_(filters.document_kinds))
    if filters.filing_forms:
        statement = statement.where(SourceDocument.filing_form.in_(filters.filing_forms))
    if filters.filing_date_from:
        statement = statement.where(SourceDocument.filing_date >= filters.filing_date_from)
    if filters.filing_date_to:
        statement = statement.where(SourceDocument.filing_date <= filters.filing_date_to)
    if filters.period_end_from:
        statement = statement.where(SourceDocument.period_end >= filters.period_end_from)
    if filters.period_end_to:
        statement = statement.where(SourceDocument.period_end <= filters.period_end_to)
    if filters.fiscal_years:
        statement = statement.where(SourceDocument.fiscal_year.in_(filters.fiscal_years))
    if filters.fiscal_periods:
        statement = statement.where(SourceDocument.fiscal_period.in_(filters.fiscal_periods))
    if filters.section_codes:
        statement = statement.where(FilingSection.section_code.in_(filters.section_codes))
    if filters.source_systems:
        statement = statement.where(SourceDocument.source_system.in_(filters.source_systems))
    return statement


def _is_sufficient(context: tuple[ContextEvidence, ...], plan: RetrievalPlan) -> bool:
    if not context:
        return False
    requested_companies = set(plan.filters.company_ids)
    if requested_companies and not requested_companies.issubset(
        {item.company_id for item in context if item.company_id is not None}
    ):
        return False
    requested_years = set(plan.filters.fiscal_years)
    return not (
        plan.comparative
        and requested_years
        and not requested_years.issubset(
            {item.fiscal_year for item in context if item.fiscal_year is not None}
        )
    )


def _truncate_evidence(item: ContextEvidence, remaining_tokens: int) -> ContextEvidence:
    if remaining_tokens <= 0:
        return item
    max_chars = remaining_tokens * 4
    content = item.content[:max_chars].rsplit(" ", 1)[0].strip()
    if not content:
        content = item.content[:max_chars]
    return item.model_copy(update={"content": content, "token_count": remaining_tokens})


def _token_count(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _period_key(item: ContextEvidence) -> str | None:
    if item.fiscal_year is not None and item.fiscal_period:
        return f"{item.fiscal_year}:{item.fiscal_period}"
    if item.fiscal_year is not None:
        return str(item.fiscal_year)
    return None


def _metric_matches(searchable: str, alias: str) -> bool:
    tokens = re.sub(r"[^\w]+", " ", alias.casefold()).strip()
    return bool(tokens and re.search(rf"(?<!\w){re.escape(tokens)}(?!\w)", searchable))


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")
