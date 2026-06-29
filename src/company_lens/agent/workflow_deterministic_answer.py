from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _deterministic_fallback_answer(
    evidence: Sequence[EvidenceEnvelope],
) -> str | None:
    if not evidence:
        return None
    lines = ["## Result"]
    calculations = tuple(item for item in evidence if item.kind is EvidenceKind.CALCULATION)
    financial_facts = _fallback_financial_facts(evidence)
    used_ids: set[str] = set()
    for item in calculations[:3]:
        sentence = _fallback_sentence(item)
        if sentence is not None:
            lines.append(f"- {sentence} [{item.evidence_id}]")
            used_ids.add(item.evidence_id)
    if financial_facts:
        lines.extend(_fallback_financial_fact_table(financial_facts))
        used_ids.update(item.evidence_id for item in financial_facts)
    preferred = sorted(
        evidence,
        key=lambda item: (
            item.kind is not EvidenceKind.CALCULATION,
            item.kind is not EvidenceKind.FINANCIAL_FACT,
            item.evidence_id,
        ),
    )
    for item in preferred:
        if financial_facts and item.kind is EvidenceKind.FINANCIAL_FACT:
            continue
        if item.evidence_id in used_ids:
            continue
        sentence = _fallback_sentence(item)
        if sentence is not None:
            lines.append(f"- {sentence} [{item.evidence_id}]")
            used_ids.add(item.evidence_id)
        if len(lines) >= 10:
            break
    return "\n".join(lines) if len(lines) > 1 else None


def _fallback_financial_facts(
    evidence: Sequence[EvidenceEnvelope],
) -> tuple[EvidenceEnvelope, ...]:
    facts = [item for item in evidence if item.kind is EvidenceKind.FINANCIAL_FACT]
    deduplicated: dict[tuple[object, ...], EvidenceEnvelope] = {}
    for item in facts:
        key = (
            item.metadata.company_id,
            item.metadata.company_name,
            item.metadata.metric,
            item.metadata.period_end,
            item.metadata.value,
            item.metadata.unit,
        )
        deduplicated.setdefault(key, item)
    return tuple(
        sorted(
            deduplicated.values(),
            key=lambda item: (item.metadata.period_end or date.min, item.evidence_id),
            reverse=True,
        )[:12]
    )


def _fallback_financial_fact_table(evidence: Sequence[EvidenceEnvelope]) -> list[str]:
    if not evidence:
        return []
    if len({item.metadata.company_name for item in evidence if item.metadata.company_name}) > 1:
        return _fallback_multi_company_financial_fact_table(evidence)
    first = min(evidence, key=lambda item: item.metadata.period_end or date.max)
    latest = max(evidence, key=lambda item: item.metadata.period_end or date.min)
    metric = latest.metadata.metric or "metric"
    lines = [
        "## Supporting facts",
        (
            f"- {metric} facts cover {_fallback_period_value(first)} through "
            f"{_fallback_period_value(latest)}. [{first.evidence_id}] [{latest.evidence_id}]"
        ),
        "",
        "| Period | Company | Metric | Value |",
        "|---|---|---|---:|",
    ]
    for item in evidence:
        value = _fallback_display_value(item.metadata.value, item.metadata.unit or "")
        if value is None:
            continue
        company = _fallback_company_name(item.metadata.company_name)
        lines.append(
            f"| {_fallback_period_value(item)} | {company} | {item.metadata.metric or 'metric'} "
            f"| {value} [{item.evidence_id}] |"
        )
    return lines

__all__ = ('_deterministic_fallback_answer', '_fallback_financial_facts', '_fallback_financial_fact_table')  # noqa: E501
