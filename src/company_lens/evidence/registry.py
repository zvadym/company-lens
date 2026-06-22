from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from urllib.parse import urlparse, urlunparse

from company_lens.evidence.schemas import (
    EvidenceEnvelope,
    SourcePreview,
    SourceStatus,
)

SourceChecker = Callable[[str], bool]


class EvidenceRegistry:
    """Immutable-by-convention registry for evidence assembled for one answer."""

    def __init__(self, evidence: Iterable[EvidenceEnvelope | Mapping[str, object]]) -> None:
        records: dict[str, EvidenceEnvelope] = {}
        for raw_item in evidence:
            item = EvidenceEnvelope.model_validate(raw_item)
            previous = records.get(item.evidence_id)
            if previous is not None and previous != item:
                raise ValueError(f"Conflicting evidence ID: {item.evidence_id}")
            records[item.evidence_id] = item
        self._records = records

    def __contains__(self, evidence_id: str) -> bool:
        return evidence_id in self._records

    def get(self, evidence_id: str) -> EvidenceEnvelope | None:
        return self._records.get(evidence_id)

    def records(self) -> tuple[EvidenceEnvelope, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def hydrate_sources(self, checker: SourceChecker | None = None) -> tuple[SourcePreview, ...]:
        previews: list[SourcePreview] = []
        for evidence in self.records():
            for source_url in evidence.source_urls:
                parsed = urlparse(source_url)
                valid_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
                if not valid_url:
                    status = SourceStatus.INVALID
                elif checker is None:
                    status = SourceStatus.UNCHECKED
                else:
                    try:
                        accessible = checker(source_url)
                    except Exception:
                        accessible = False
                    status = SourceStatus.AVAILABLE if accessible else SourceStatus.INACCESSIBLE
                exact_url = source_url
                if valid_url and evidence.metadata.page_start is not None:
                    exact_url = urlunparse(
                        parsed._replace(fragment=f"page={evidence.metadata.page_start}")
                    )
                elif valid_url and evidence.metadata.section_id is not None:
                    exact_url = urlunparse(
                        parsed._replace(fragment=f"section={evidence.metadata.section_id}")
                    )
                previews.append(
                    SourcePreview(
                        evidence_id=evidence.evidence_id,
                        title=evidence.summary[:160],
                        kind=evidence.kind,
                        source_url=source_url,
                        exact_url=exact_url,
                        status=status,
                        page_start=evidence.metadata.page_start,
                        page_end=evidence.metadata.page_end,
                        section_id=evidence.metadata.section_id,
                    )
                )
        return tuple(previews)
