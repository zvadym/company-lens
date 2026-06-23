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
FINANCIAL_ABBREVIATIONS = (
    "Co.",
    "Cos.",
    "LLC.",
    "L.L.C.",
    "LP.",
    "L.P.",
    "N.A.",
    "No.",
    "S.A.",
    "U.K.",
    "U.S.",
    "U.S.A.",
)
SEC_ITEM_LABEL_PATTERN = re.compile(
    r"\bItem\s+(?:\d{1,2}[A-Z]?|[IVX]+)\.(?=\s+[A-Z][A-Za-z&/(), -]*)",
    re.IGNORECASE,
)
SEC_PART_LABEL_PATTERN = re.compile(r"\bPart\s+(?:[IVX]+|\d+)\.(?=\s+|$)", re.IGNORECASE)
SEC_LABEL_FRAGMENT_PATTERN = re.compile(
    r"\b(?:Item\s+(?:\d{1,2}[A-Z]?|[IVX]+)|Part\s+(?:[IVX]+|\d+))\.\s*(?:\*\*)?$",
    re.IGNORECASE,
)
STRUCTURAL_FRAGMENT_PREFIX_PATTERN = re.compile(
    r"(?:^|\b)(?:"
    r"коротко\s+по\s+суті|"
    r"(?:у|в)\s+розділі|"
    r"(?:in|under)\s+(?:the\s+)?section|"
    r"section|розділ|розділі|пункт|"
    r"(?:у|в)\s+\**(?:item|part)\b"
    r")",
    re.IGNORECASE,
)
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
        material = not bool(NON_MATERIAL_PATTERN.fullmatch(text))
        if not evidence_ids and _is_structural_fragment(text):
            material = False
        claims.append(
            ClaimRecord(
                claim_id=f"claim:{digest}",
                text=text,
                evidence_ids=evidence_ids,
                material=material,
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
        protected, replacements = _protect_sentence_boundaries(content)
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
    return tuple(_merge_structural_fragments(segments))


def _is_table_row(line: str) -> bool:
    return line.count("|") >= 2


def _protect_sentence_boundaries(content: str) -> tuple[str, dict[str, str]]:
    protected = content
    replacements: dict[str, str] = {}
    for offset, abbreviation in enumerate((*ABBREVIATIONS, *FINANCIAL_ABBREVIATIONS)):
        placeholder = f"__abbr_{offset}__"
        protected = protected.replace(abbreviation, placeholder)
        replacements[placeholder] = abbreviation

    for pattern in (SEC_ITEM_LABEL_PATTERN, SEC_PART_LABEL_PATTERN):
        protected = pattern.sub(lambda match: _protect_match(match, replacements), protected)
    return protected, replacements


def _protect_match(match: re.Match[str], replacements: dict[str, str]) -> str:
    value = match.group(0)
    placeholder = f"__protected_period_{len(replacements)}__"
    replacements[placeholder] = "."
    return value.replace(".", placeholder)


def _merge_structural_fragments(segments: list[str]) -> list[str]:
    merged: list[str] = []
    index = 0
    while index < len(segments):
        segment = segments[index]
        if (
            index + 1 < len(segments)
            and not CITATION_PATTERN.search(segment)
            and _is_structural_fragment(segment)
        ):
            merged.append(f"{segment} {segments[index + 1]}")
            index += 2
            continue
        merged.append(segment)
        index += 1
    return merged


def _is_structural_fragment(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) > 120 or not SEC_LABEL_FRAGMENT_PATTERN.search(stripped):
        return False
    if stripped.count("**") % 2 == 1:
        return True
    return bool(STRUCTURAL_FRAGMENT_PREFIX_PATTERN.search(stripped))
