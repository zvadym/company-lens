from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _invalid_claim_previews(
    claims: Sequence[ClaimRecord], issues: Sequence[ValidationIssue]
) -> tuple[dict[str, object], ...]:
    issue_claim_ids = {issue.claim_id for issue in issues if issue.claim_id is not None}
    return tuple(
        {
            "claim_id": claim.claim_id,
            "text": claim.text[:500],
            "evidence_ids": claim.evidence_ids,
        }
        for claim in claims
        if claim.claim_id in issue_claim_ids
    )


def _compact_evidence_context(
    evidence: Sequence[EvidenceEnvelope],
) -> tuple[dict[str, object], ...]:
    compact: list[dict[str, object]] = []
    for item in evidence:
        display_value = _display_value(item.metadata.value, item.metadata.unit or "")
        metadata = item.metadata.model_dump(mode="json", exclude_none=True)
        if display_value is not None:
            # The LLM context should expose presentation-ready numbers while the
            # EvidenceEnvelope itself keeps raw Decimals for deterministic validation.
            metadata.pop("value", None)
            metadata["display_value"] = display_value
        record: dict[str, object] = {
            "evidence_id": item.evidence_id,
            "kind": item.kind.value,
            "summary": _normalize_answer_number_formatting(
                sanitize_untrusted_text(item.summary)
                if item.kind is EvidenceKind.DOCUMENT
                else item.summary
            ),
            "display_summary": _display_summary(item),
            "lineage_refs": item.lineage_refs,
            "metadata": metadata,
        }
        if item.kind is EvidenceKind.DOCUMENT:
            record["trust"] = "untrusted_external_data"
            record["prompt_injection_flags"] = prompt_injection_flags(item.summary)
        if item.kind is EvidenceKind.CALCULATION:
            record["calculation"] = {
                "values": _compact_numeric_payload_points(
                    item.payload.get("values", ()),
                    item.metadata.unit or "",
                ),
                "inputs": _compact_numeric_payload_points(item.payload.get("inputs", ()), ""),
            }
        compact.append(record)
    return tuple(compact)


def _display_summary(item: EvidenceEnvelope) -> str:
    if item.kind is EvidenceKind.FINANCIAL_FACT:
        metric = item.metadata.metric or "metric"
        company = _fallback_company_name(item.metadata.company_name)
        period = _fallback_period(item)
        value = _display_value(item.metadata.value, item.metadata.unit or "")
        if value is not None:
            return f"{company} {metric}: {value}{period}"
    if item.kind is EvidenceKind.MACRO_OBSERVATION:
        period = _fallback_period(item)
        value = _display_value(item.metadata.value, item.metadata.unit or "")
        if value is not None:
            return f"Macro observation: {value}{period}"
    if item.kind is EvidenceKind.CALCULATION:
        sentence = _fallback_calculation_sentence(item)
        if sentence is not None:
            return sentence
    return _normalize_answer_number_formatting(item.summary)


def _calculation_display_summary(result: CalculationResult) -> str:
    values = tuple(
        point for point in result.values if _display_value(point.value, result.unit) is not None
    )
    operation = _fallback_operation_label(result.operation)
    if not values:
        return f"{operation} was calculated."
    latest = max(values, key=lambda point: point.observed_at or date.min)
    latest_value = _display_value(latest.value, result.unit)
    latest_period = (
        f" at {latest.observed_at.isoformat()}" if latest.observed_at is not None else ""
    )
    if len(values) == 1:
        return f"{operation}: {latest_value}{latest_period}"
    first_date = min(
        (point.observed_at for point in values if point.observed_at is not None),
        default=None,
    )
    latest_date = max(
        (point.observed_at for point in values if point.observed_at is not None),
        default=None,
    )
    if first_date is not None and latest_date is not None and first_date != latest_date:
        return (
            f"{operation}: latest {latest_value}{latest_period}; covers "
            f"{first_date.isoformat()} through {latest_date.isoformat()}"
        )
    return f"{operation}: latest {latest_value}{latest_period}"


def _compact_numeric_payload_points(
    value: object, default_unit: str
) -> tuple[dict[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    points: list[dict[str, object]] = []
    for point in value:
        if not isinstance(point, dict):
            continue
        raw_value = _payload_decimal(point.get("value"))
        unit = point.get("unit")
        unit_text = unit if isinstance(unit, str) else default_unit
        record: dict[str, object] = {
            "label": point.get("label"),
            "observed_at": point.get("observed_at"),
        }
        display_value = _display_value(raw_value, unit_text)
        if display_value is not None:
            record["display_value"] = display_value
        points.append({key: item for key, item in record.items() if item is not None})
    return tuple(points)


__all__ = (
    "_invalid_claim_previews",
    "_compact_evidence_context",
    "_display_summary",
    "_calculation_display_summary",
    "_compact_numeric_payload_points",
)  # noqa: E501
