from __future__ import annotations

import hashlib
import re

from company_lens.evidence.schemas import ClaimRecord

CITATION_PATTERN = re.compile(r"\[([a-z][a-z0-9_.:-]*)\]")
LEADING_CITATIONS_PATTERN = re.compile(
    r"^(?P<citations>(?:\[[a-z][a-z0-9_.:-]*\]\s*)+)(?P<remainder>.*)$"
)
SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
TABLE_SEPARATOR_PATTERN = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(?P<text>.+?)\s*#*\s*$")
LIST_MARKER_PATTERN = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
HORIZONTAL_RULE_PATTERN = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
FACTUAL_HEADING_PATTERN = re.compile(r"\d|\[[a-z][a-z0-9_.:-]*\]")
ABBREVIATIONS = ("vs.", "e.g.", "i.e.", "Inc.", "Corp.", "Ltd.")
NON_MATERIAL_PATTERN = re.compile(
    r"^(?:note|sources?|limitations?|insufficient evidence)\s*:?$", re.IGNORECASE
)


def extract_claims(answer: str) -> tuple[ClaimRecord, ...]:
    """Extract stable sentence-level claims and their inline evidence IDs."""

    claims: list[ClaimRecord] = []
    for raw_segment in _claim_segments(answer):
        segment = raw_segment.strip()
        if not segment:
            continue
        evidence_ids = tuple(dict.fromkeys(CITATION_PATTERN.findall(segment)))
        text = CITATION_PATTERN.sub("", segment).strip()
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        if not text:
            continue
        sentence_index = len(claims)
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


def _claim_segments(answer: str) -> tuple[str, ...]:
    lines = answer.strip().splitlines()
    segments: list[str] = []
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line or HORIZONTAL_RULE_PATTERN.fullmatch(line):
            continue
        if TABLE_SEPARATOR_PATTERN.fullmatch(line):
            continue
        if _is_table_row(line):
            next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
            if TABLE_SEPARATOR_PATTERN.fullmatch(next_line):
                continue
            segments.append(line.strip("|").strip())
            continue
        heading = HEADING_PATTERN.fullmatch(line)
        if heading is not None:
            heading_text = heading.group("text")
            if FACTUAL_HEADING_PATTERN.search(heading_text):
                segments.append(heading_text)
            continue
        content = LIST_MARKER_PATTERN.sub("", line)
        protected = content
        replacements: dict[str, str] = {}
        for offset, abbreviation in enumerate(ABBREVIATIONS):
            placeholder = f"__abbr_{offset}__"
            protected = protected.replace(abbreviation, placeholder)
            replacements[placeholder] = abbreviation
        for sentence in SENTENCE_PATTERN.split(protected):
            restored = sentence
            for placeholder, abbreviation in replacements.items():
                restored = restored.replace(placeholder, abbreviation)
            leading_citations = LEADING_CITATIONS_PATTERN.fullmatch(restored.strip())
            if leading_citations is not None and segments:
                segments[-1] = f"{segments[-1]} {leading_citations.group('citations').strip()}"
                restored = leading_citations.group("remainder")
            if restored.strip():
                segments.append(restored.strip())
    return tuple(segments)


def _is_table_row(line: str) -> bool:
    return line.count("|") >= 2
