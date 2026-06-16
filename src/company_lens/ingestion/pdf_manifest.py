from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class InvestorPdfManifestDocument:
    company_name: str
    source_url: str
    title: str
    document_type: str
    manifest_id: str | None = None
    ticker: str | None = None
    cik: str | None = None
    period_end: date | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    metadata: dict[str, Any] | None = None


def load_investor_pdf_manifest(path: Path) -> tuple[InvestorPdfManifestDocument, ...]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise ValueError("Investor PDF manifest must contain a 'documents' list.")

    parsed: list[InvestorPdfManifestDocument] = []
    for index, item in enumerate(documents):
        if not isinstance(item, dict):
            raise ValueError(f"Investor PDF manifest entry {index} must be an object.")
        parsed.append(_parse_document(item, index))
    return tuple(parsed)


def _parse_document(item: dict[str, Any], index: int) -> InvestorPdfManifestDocument:
    company_name = _required_str(item, "company_name", index)
    source_url = _required_str(item, "url", index)
    title = _required_str(item, "title", index)
    document_type = _required_str(item, "document_type", index)
    metadata = item.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError(f"Investor PDF manifest entry {index} metadata must be an object.")

    return InvestorPdfManifestDocument(
        company_name=company_name,
        source_url=source_url,
        title=title,
        document_type=document_type,
        manifest_id=_optional_str(item.get("id")),
        ticker=_optional_str(item.get("ticker")),
        cik=_normalize_cik(_optional_str(item.get("cik"))),
        period_end=_optional_date(item.get("period_end"), index),
        fiscal_year=_optional_int(item.get("fiscal_year"), "fiscal_year", index),
        fiscal_period=_optional_str(item.get("fiscal_period")),
        metadata=dict(metadata or {}),
    )


def _required_str(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Investor PDF manifest entry {index} requires non-empty '{key}'.")
    return value.strip()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    normalized = value.strip()
    return normalized or None


def _optional_int(value: object, key: str, index: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ValueError(f"Investor PDF manifest entry {index} has invalid '{key}'.")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Investor PDF manifest entry {index} has invalid '{key}'.") from exc


def _optional_date(value: object, index: int) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"Investor PDF manifest entry {index} period_end must be YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Investor PDF manifest entry {index} period_end must be YYYY-MM-DD."
        ) from exc


def _normalize_cik(value: str | None) -> str | None:
    if value is None:
        return None
    return value.zfill(10)
