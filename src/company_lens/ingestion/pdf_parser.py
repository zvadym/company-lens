from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from typing import Any

import pdfplumber

PDF_COORDINATE_SYSTEM = "pdfplumber_top_left_points"


class PdfParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedPdfBlock:
    block_index: int
    block_type: str
    text: str | None
    text_hash: str | None
    x0_points: Decimal | None
    y0_points: Decimal | None
    x1_points: Decimal | None
    y1_points: Decimal | None
    char_start: int | None
    char_end: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ParsedPdfPage:
    page_number: int
    text: str | None
    text_hash: str | None
    width_points: Decimal | None
    height_points: Decimal | None
    blocks: tuple[ParsedPdfBlock, ...]
    diagnostics: dict[str, Any]


@dataclass(frozen=True)
class ParsedPdf:
    page_count: int
    pages: tuple[ParsedPdfPage, ...]
    diagnostics: dict[str, Any]


class PdfParser:
    def parse(self, content: bytes) -> ParsedPdf:
        try:
            with pdfplumber.open(BytesIO(content)) as pdf:
                pages = tuple(
                    self._parse_page(page, page_number)
                    for page_number, page in enumerate(pdf.pages, start=1)
                )
        except Exception as exc:
            raise PdfParseError(f"Could not parse PDF: {exc}") from exc

        if not pages:
            raise PdfParseError("PDF has no pages.")

        empty_pages = [page.page_number for page in pages if not _has_text(page.text)]
        pages_without_blocks = [page.page_number for page in pages if not page.blocks]
        image_only = len(empty_pages) == len(pages)
        diagnostics: dict[str, Any] = {
            "parser": "pdfplumber",
            "page_count": len(pages),
            "empty_pages": empty_pages,
            "pages_without_blocks": pages_without_blocks,
            "image_only_or_scanned": image_only,
            "coordinate_system": PDF_COORDINATE_SYSTEM,
        }
        return ParsedPdf(page_count=len(pages), pages=pages, diagnostics=diagnostics)

    def _parse_page(self, page: Any, page_number: int) -> ParsedPdfPage:
        text = page.extract_text() or ""
        words = page.extract_words(
            keep_blank_chars=False,
            use_text_flow=True,
            extra_attrs=[],
        )
        blocks = tuple(_build_line_blocks(words, text))
        diagnostics = {
            "empty_text": not _has_text(text),
            "block_count": len(blocks),
            "word_count": len(words),
        }
        return ParsedPdfPage(
            page_number=page_number,
            text=text or None,
            text_hash=_hash_text(text),
            width_points=_decimal_or_none(page.width),
            height_points=_decimal_or_none(page.height),
            blocks=blocks,
            diagnostics=diagnostics,
        )


def _build_line_blocks(words: Iterable[dict[str, Any]], page_text: str) -> list[ParsedPdfBlock]:
    sorted_words = sorted(words, key=lambda word: (float(word["top"]), float(word["x0"])))
    line_groups: list[list[dict[str, Any]]] = []
    current_line: list[dict[str, Any]] = []
    current_top: float | None = None

    for word in sorted_words:
        word_top = float(word["top"])
        if current_top is None or abs(word_top - current_top) <= 3.0:
            current_line.append(word)
            current_top = word_top if current_top is None else current_top
            continue
        line_groups.append(current_line)
        current_line = [word]
        current_top = word_top

    if current_line:
        line_groups.append(current_line)

    blocks: list[ParsedPdfBlock] = []
    search_offset = 0
    for index, line in enumerate(line_groups):
        text = " ".join(str(word["text"]) for word in line).strip()
        if not text:
            continue
        found_at = page_text.find(text, search_offset) if page_text else -1
        if found_at >= 0:
            char_start: int | None = found_at
            next_search_offset = found_at + len(text)
            char_end: int | None = next_search_offset
            search_offset = next_search_offset
        else:
            char_start = None
            char_end = None
        blocks.append(
            ParsedPdfBlock(
                block_index=index,
                block_type="text_line",
                text=text,
                text_hash=_hash_text(text),
                x0_points=_decimal_or_none(min(float(word["x0"]) for word in line)),
                y0_points=_decimal_or_none(min(float(word["top"]) for word in line)),
                x1_points=_decimal_or_none(max(float(word["x1"]) for word in line)),
                y1_points=_decimal_or_none(max(float(word["bottom"]) for word in line)),
                char_start=char_start,
                char_end=char_end,
                metadata={
                    "coordinate_system": PDF_COORDINATE_SYSTEM,
                    "word_count": len(line),
                },
            )
        )
    return blocks


def _has_text(text: str | None) -> bool:
    return bool(text and text.strip())


def _hash_text(text: str | None) -> str | None:
    if not _has_text(text):
        return None
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))
