from __future__ import annotations

import hashlib
import re

from company_lens.evidence.schemas import ClaimRecord

CITATION_PATTERN = re.compile(r"\[([a-z][a-z0-9_.:-]*)\]")
SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
NON_MATERIAL_PATTERN = re.compile(
    r"^(?:note|sources?|limitations?|insufficient evidence)\s*:?$", re.IGNORECASE
)


def extract_claims(answer: str) -> tuple[ClaimRecord, ...]:
    """Extract stable sentence-level claims and their inline evidence IDs."""

    claims: list[ClaimRecord] = []
    for sentence_index, raw_segment in enumerate(SENTENCE_PATTERN.split(answer.strip())):
        segment = raw_segment.strip()
        if not segment:
            continue
        evidence_ids = tuple(dict.fromkeys(CITATION_PATTERN.findall(segment)))
        text = CITATION_PATTERN.sub("", segment).strip()
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        if not text:
            continue
        digest = hashlib.sha256(f"{sentence_index}:{text}".encode()).hexdigest()[:16]
        claims.append(
            ClaimRecord(
                claim_id=f"claim:{digest}",
                text=text,
                evidence_ids=evidence_ids,
                material=not bool(NON_MATERIAL_PATTERN.fullmatch(text)),
                sentence_index=sentence_index,
            )
        )
    return tuple(claims)
