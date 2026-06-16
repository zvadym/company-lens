from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass(frozen=True)
class DetectedSection:
    section_key: str
    title: str
    start_offset: int
    end_offset: int
    text_hash: str


SECTION_PATTERNS = {
    "business": (
        "Business",
        re.compile(r"\bitem\s+1[\.\s:-]+business\b", re.IGNORECASE),
    ),
    "risk_factors": (
        "Risk Factors",
        re.compile(r"\bitem\s+1a[\.\s:-]+risk\s+factors\b", re.IGNORECASE),
    ),
    "mda": (
        "Management's Discussion and Analysis",
        re.compile(
            r"\bitem\s+7[\.\s:-]+management.?s\s+discussion\s+and\s+analysis\b",
            re.IGNORECASE,
        ),
    ),
    "liquidity": (
        "Liquidity and Capital Resources",
        re.compile(r"\bliquidity\s+and\s+capital\s+resources\b", re.IGNORECASE),
    ),
    "market_risk": (
        "Market Risk",
        re.compile(
            r"\bitem\s+7a[\.\s:-]+quantitative\s+and\s+qualitative\s+disclosures\b"
            r"|\bitem\s+3[\.\s:-]+quantitative\s+and\s+qualitative\s+disclosures\b",
            re.IGNORECASE,
        ),
    ),
    "competition": (
        "Competition",
        re.compile(r"\bcompetition\b", re.IGNORECASE),
    ),
    "strategy_outlook": (
        "Strategy and Outlook",
        re.compile(r"\b(strategy|outlook)\b", re.IGNORECASE),
    ),
}

NEXT_ITEM_PATTERN = re.compile(r"\bitem\s+(?:1a|1b|2|3|4|5|6|7|7a|8|9|9a|9b)\b", re.IGNORECASE)
MIN_SECTION_BODY_CHARS = 500


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = data.strip()
        if cleaned:
            self._chunks.append(cleaned)

    def text(self) -> str:
        return "\n".join(self._chunks)


def detect_high_value_sections(
    content: bytes, *, content_type: str | None = None
) -> list[DetectedSection]:
    text = _decode_content(content)
    if _looks_like_html(content_type, text):
        parser = _TextExtractor()
        parser.feed(text)
        text = parser.text()
    normalized_text = re.sub(r"[ \t\r\f\v]+", " ", text)

    hits: list[tuple[str, str, int]] = []
    for section_key, (title, pattern) in SECTION_PATTERNS.items():
        match = _best_section_match(normalized_text, pattern)
        if match is not None:
            hits.append((section_key, title, match))

    ordered_hits = sorted(hits, key=lambda hit: hit[2])
    sections: list[DetectedSection] = []
    for index, (section_key, title, start_offset) in enumerate(ordered_hits):
        next_start = (
            ordered_hits[index + 1][2] if index + 1 < len(ordered_hits) else len(normalized_text)
        )
        item_boundary = NEXT_ITEM_PATTERN.search(normalized_text, start_offset + 1, next_start)
        end_offset = item_boundary.start() if item_boundary is not None else next_start
        section_text = normalized_text[start_offset:end_offset].strip()
        if not section_text:
            continue
        sections.append(
            DetectedSection(
                section_key=section_key,
                title=title,
                start_offset=start_offset,
                end_offset=end_offset,
                text_hash=hashlib.sha256(section_text.encode("utf-8")).hexdigest(),
            )
        )
    return sections


def _decode_content(content: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _looks_like_html(content_type: str | None, text: str) -> bool:
    if content_type and "html" in content_type.lower():
        return True
    return "<html" in text[:500].lower() or "<document" in text[:500].lower()


def _best_section_match(text: str, pattern: re.Pattern[str]) -> int | None:
    fallback: int | None = None
    for match in pattern.finditer(text):
        start_offset = match.start()
        fallback = start_offset
        next_item = NEXT_ITEM_PATTERN.search(text, match.end())
        end_offset = next_item.start() if next_item is not None else len(text)
        if end_offset - start_offset >= MIN_SECTION_BODY_CHARS:
            return start_offset
    return fallback
