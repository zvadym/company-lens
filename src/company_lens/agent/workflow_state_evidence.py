from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _evidence_from_state(state: AgentState) -> tuple[EvidenceEnvelope, ...]:
    evidence: list[EvidenceEnvelope] = []
    for retrieval_branch in state.get("retrieval_results", ()):
        for context_item in retrieval_branch.result.context:
            evidence.append(
                EvidenceEnvelope(
                    evidence_id=context_item.citation_label,
                    kind=EvidenceKind.DOCUMENT,
                    summary=context_item.content,
                    source_urls=(context_item.source_url,),
                    lineage_refs=(retrieval_branch.branch_id, context_item.source_id),
                    metadata=EvidenceMetadata(
                        company_id=context_item.company_id,
                        company_name=context_item.company_name,
                        document_version_id=context_item.document_version_id,
                        section_id=context_item.section_id,
                        chunk_id=context_item.chunk_id,
                        financial_fact_id=context_item.financial_fact_id,
                        fiscal_year=context_item.fiscal_year,
                        fiscal_period=context_item.fiscal_period,
                        page_start=context_item.page_start,
                        page_end=context_item.page_end,
                    ),
                    payload=context_item.model_dump(mode="json"),
                )
            )
    for financial_branch in state.get("financial_results", ()):
        for fact in financial_branch.result.observations:
            display_value = _display_value(fact.value, fact.unit) or f"{fact.value} {fact.unit}"
            evidence.append(
                EvidenceEnvelope(
                    evidence_id=f"financial_fact:{fact.id}",
                    kind=EvidenceKind.FINANCIAL_FACT,
                    summary=(
                        f"{fact.company_name} {fact.metric}: {display_value} "
                        f"at {fact.period_end.isoformat()}"
                    ),
                    source_urls=(fact.source_url,),
                    lineage_refs=(financial_branch.branch_id,),
                    metadata=EvidenceMetadata(
                        company_id=fact.company_id,
                        company_name=fact.company_name,
                        financial_fact_id=fact.id,
                        metric=fact.metric,
                        period_start=fact.period_start,
                        period_end=fact.period_end,
                        fiscal_year=fact.fiscal_year,
                        fiscal_period=fact.fiscal_period,
                        unit=fact.unit,
                        value=fact.value,
                    ),
                    payload=fact.model_dump(mode="json"),
                )
            )
    default_chart_macro_keys = _default_chart_macro_evidence_keys(state)
    for macro_branch in state.get("macro_results", ()):
        for observation in macro_branch.result.observations:
            if observation.is_missing or observation.value is None:
                continue
            display_value = (
                _display_value(observation.value, observation.unit)
                or f"{observation.value} {observation.unit}"
            )
            macro_key = (macro_branch.branch_id, observation.series_id, observation.observed_at)
            if default_chart_macro_keys is not None and macro_key not in default_chart_macro_keys:
                continue
            evidence.append(
                EvidenceEnvelope(
                    evidence_id=(
                        f"macro:{observation.series_id.lower()}:"
                        f"{observation.observed_at.isoformat()}"
                    ),
                    kind=EvidenceKind.MACRO_OBSERVATION,
                    summary=(
                        f"{observation.series_id}: {display_value} "
                        f"at {observation.observed_at.isoformat()}"
                    ),
                    source_urls=(observation.source_url,),
                    lineage_refs=(macro_branch.branch_id,),
                    metadata=EvidenceMetadata(
                        macro_observation_id=observation.id,
                        period_start=observation.observed_at,
                        period_end=observation.observed_at,
                        unit=observation.unit,
                        value=observation.value,
                    ),
                    payload=observation.model_dump(mode="json"),
                )
            )
    plan = state.get("execution_plan")
    calculations_by_id = {item.branch_id: item for item in state.get("calculations", ())}
    for branch_id, calculation in calculations_by_id.items():
        plan_branch = (
            next(
                (
                    branch
                    for branch in plan.branches
                    if isinstance(branch, CalculationBranch) and branch.branch_id == branch_id
                ),
                None,
            )
            if plan
            else None
        )
        input_evidence_ids = _input_evidence_ids(
            plan_branch.input_refs if plan_branch else (), state
        )
        input_records = tuple(
            item for item in evidence if item.evidence_id in set(input_evidence_ids)
        )
        company_ids = {
            item.metadata.company_id
            for item in input_records
            if item.metadata.company_id is not None
        }
        company_names = {
            item.metadata.company_name
            for item in input_records
            if item.metadata.company_name is not None
        }
        metrics = {
            item.metadata.metric for item in input_records if item.metadata.metric is not None
        }
        period_starts = tuple(
            item.metadata.period_start
            for item in input_records
            if item.metadata.period_start is not None
        )
        period_ends = tuple(
            item.metadata.period_end
            for item in input_records
            if item.metadata.period_end is not None
        )
        result_value = (
            calculation.result.values[0].value if len(calculation.result.values) == 1 else None
        )
        evidence.append(
            EvidenceEnvelope(
                evidence_id=f"calculation:{branch_id}",
                kind=EvidenceKind.CALCULATION,
                summary=_calculation_display_summary(calculation.result),
                source_urls=calculation.result.sources,
                lineage_refs=input_evidence_ids,
                metadata=EvidenceMetadata(
                    company_id=next(iter(company_ids)) if len(company_ids) == 1 else None,
                    company_name=(next(iter(company_names)) if len(company_names) == 1 else None),
                    metric=next(iter(metrics)) if len(metrics) == 1 else None,
                    period_start=min(period_starts) if period_starts else None,
                    period_end=max(period_ends) if period_ends else None,
                    unit=calculation.result.unit,
                    value=result_value,
                    formula=calculation.result.formula,
                    operation=calculation.result.operation,
                ),
                payload=calculation.result.model_dump(mode="json"),
            )
        )
    deduplicated = {item.evidence_id: item for item in evidence}
    return tuple(deduplicated[key] for key in sorted(deduplicated))


def _input_evidence_ids(references: tuple[str, ...], state: AgentState) -> tuple[str, ...]:
    evidence_ids: list[str] = []
    retrieval_by_branch = {
        item.branch_id: item.result for item in state.get("retrieval_results", ())
    }
    financial_by_branch = {
        item.branch_id: item.result for item in state.get("financial_results", ())
    }
    macro_by_branch = {item.branch_id: item.result for item in state.get("macro_results", ())}
    calculation_branches = {item.branch_id for item in state.get("calculations", ())}
    for reference in references:
        if reference in retrieval_by_branch:
            evidence_ids.extend(
                item.citation_label for item in retrieval_by_branch[reference].context
            )
        elif reference in financial_by_branch:
            evidence_ids.extend(
                f"financial_fact:{item.id}" for item in financial_by_branch[reference].observations
            )
        elif reference in macro_by_branch:
            evidence_ids.extend(
                f"macro:{item.series_id.lower()}:{item.observed_at.isoformat()}"
                for item in macro_by_branch[reference].observations
                if not item.is_missing and item.value is not None
            )
        elif reference in calculation_branches:
            evidence_ids.append(f"calculation:{reference}")
    return tuple(dict.fromkeys(evidence_ids))


__all__ = ("_evidence_from_state", "_input_evidence_ids")
