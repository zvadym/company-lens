from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _fallback_multi_company_financial_fact_table(
    evidence: Sequence[EvidenceEnvelope],
) -> list[str]:
    first = min(evidence, key=lambda item: item.metadata.period_end or date.max)
    latest = max(evidence, key=lambda item: item.metadata.period_end or date.min)
    metric = latest.metadata.metric or "metric"
    companies = tuple(
        sorted(
            {
                _fallback_company_name(item.metadata.company_name)
                for item in evidence
                if item.metadata.company_name is not None
            }
        )
    )
    grouped: dict[tuple[date | None, str], dict[str, EvidenceEnvelope]] = {}
    for item in evidence:
        company = _fallback_company_name(item.metadata.company_name)
        key = (item.metadata.period_end, item.metadata.metric or "metric")
        grouped.setdefault(key, {})
        grouped[key].setdefault(company, item)
    lines = [
        "## Supporting facts",
        (
            f"- {metric} facts cover {_fallback_period_value(first)} through "
            f"{_fallback_period_value(latest)}. [{first.evidence_id}] [{latest.evidence_id}]"
        ),
        "",
        f"| Period | Metric | {' | '.join(companies)} |",
        f"|---|---|{'|'.join('---:' for _ in companies)}|",
    ]
    for period_end, row_metric in sorted(
        grouped,
        key=lambda item: (item[0] or date.min, item[1]),
        reverse=True,
    ):
        row = grouped[(period_end, row_metric)]
        values = [_fallback_financial_fact_cell(row.get(company)) for company in companies]
        period = period_end.isoformat() if period_end is not None else "available period"
        lines.append(f"| {period} | {row_metric} | {' | '.join(values)} |")
    return lines


def _fallback_financial_fact_cell(item: EvidenceEnvelope | None) -> str:
    if item is None:
        return ""
    value = _fallback_display_value(item.metadata.value, item.metadata.unit or "")
    if value is None:
        return f"[{item.evidence_id}]"
    return f"{value} [{item.evidence_id}]"


def _fallback_sentence(item: EvidenceEnvelope) -> str | None:
    if item.kind is EvidenceKind.CALCULATION:
        return _fallback_calculation_sentence(item)
    if item.kind is EvidenceKind.FINANCIAL_FACT:
        metric = item.metadata.metric or "metric"
        company = _fallback_company_name(item.metadata.company_name)
        period = _fallback_period(item)
        value = _fallback_decimal(item.metadata.value)
        unit = item.metadata.unit or ""
        if value is None:
            return item.summary
        value_with_unit = _fallback_value_with_unit(value, unit, item.metadata.value)
        return f"{company} {metric} was {value_with_unit}{period}."
    if item.kind is EvidenceKind.MACRO_OBSERVATION:
        period = _fallback_period(item)
        value = _fallback_decimal(item.metadata.value)
        unit = item.metadata.unit or ""
        if value is None:
            return item.summary
        value_with_unit = _fallback_value_with_unit(value, unit, item.metadata.value)
        return f"The macro observation was {value_with_unit}{period}."
    if item.kind is EvidenceKind.DOCUMENT:
        return item.summary
    return None


def _fallback_calculation_sentence(item: EvidenceEnvelope) -> str | None:
    operation = _fallback_operation_label(item.metadata.operation)
    company = _fallback_company_name(item.metadata.company_name)
    metric = item.metadata.metric or "metric"
    value = _fallback_decimal(item.metadata.value)
    unit = item.metadata.unit or ""
    period = _fallback_period(item)
    if value is None:
        points = _fallback_calculation_points(item)
        if not points:
            return f"{company} {metric} {operation} was calculated."
        latest = max(points, key=lambda point: point[0] or date.min)
        latest_value = _fallback_value_with_unit(
            _fallback_decimal(latest[1]) or str(latest[1]),
            unit,
            latest[1],
        )
        latest_period = f" at {latest[0].isoformat()}" if latest[0] is not None else ""
        covered_period = _fallback_calculation_period(points)
        return (
            f"{company} {metric} {operation} covered {covered_period}; latest value was "
            f"{latest_value}{latest_period}."
        )
    value_with_unit = _fallback_value_with_unit(value, unit, item.metadata.value)
    return f"{company} {metric} {operation} was {value_with_unit}{period}."


def _fallback_calculation_points(
    item: EvidenceEnvelope,
) -> tuple[tuple[date | None, Decimal, str | None], ...]:
    values = item.payload.get("values")
    if not isinstance(values, (list, tuple)):
        return ()
    points: list[tuple[date | None, Decimal, str | None]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        raw_value = _payload_decimal(value.get("value"))
        if raw_value is None:
            continue
        label = value.get("label")
        points.append(
            (
                _payload_date(value.get("observed_at")),
                raw_value,
                label if isinstance(label, str) else None,
            )
        )
    return tuple(points)

__all__ = ('_fallback_multi_company_financial_fact_table', '_fallback_financial_fact_cell', '_fallback_sentence', '_fallback_calculation_sentence', '_fallback_calculation_points')  # noqa: E501
