from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser

import tiktoken

TOKEN_ENCODING_NAME = "cl100k_base"
TOKEN_ENCODING = tiktoken.get_encoding(TOKEN_ENCODING_NAME)


@dataclass(frozen=True)
class TextSpan:
    text: str
    char_start: int
    char_end: int
    page_start: int | None = None
    page_end: int | None = None


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


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_hash(prompt: str) -> str:
    return content_hash(prompt)


def decode_document_content(content: bytes, *, content_type: str | None = None) -> str:
    text = _decode_bytes(content)
    if _looks_like_html(content_type, text):
        parser = _TextExtractor()
        parser.feed(text)
        text = parser.text()
    return normalize_document_text(text)


def normalize_document_text(text: str) -> str:
    normalized = text.replace("\x00", " ")
    normalized = re.sub(r"[ \t\r\f\v]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def normalize_for_fingerprint(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return " ".join(words)


def estimate_token_count(text: str) -> int:
    return len(TOKEN_ENCODING.encode(text))


def split_sentences(text: str) -> list[str]:
    candidates = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text.strip())
    return [candidate.strip() for candidate in candidates if candidate.strip()]


def paragraph_spans(text: str) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, flags=re.DOTALL):
        paragraph = normalize_document_text(match.group(0))
        if paragraph:
            spans.append(TextSpan(text=paragraph, char_start=match.start(), char_end=match.end()))
    return spans or [TextSpan(text=text, char_start=0, char_end=len(text))]


def fixed_token_chunks(
    text: str,
    *,
    max_tokens: int,
    overlap_tokens: int,
    base_char_start: int = 0,
    page_start: int | None = None,
    page_end: int | None = None,
) -> list[TextSpan]:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive.")
    if overlap_tokens < 0:
        raise ValueError("overlap_tokens must be non-negative.")
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens.")

    token_ids = TOKEN_ENCODING.encode(text)
    if not token_ids:
        return []
    decoded, offsets = TOKEN_ENCODING.decode_with_offsets(token_ids)
    if decoded != text:
        raise ValueError("Token encoding did not round-trip the source text.")

    chunks: list[TextSpan] = []
    start_index = 0
    while start_index < len(token_ids):
        end_index = min(len(token_ids), start_index + max_tokens)
        while end_index > start_index:
            char_start = offsets[start_index]
            char_end = offsets[end_index] if end_index < len(offsets) else len(text)
            raw_chunk = text[char_start:char_end]
            leading_whitespace = len(raw_chunk) - len(raw_chunk.lstrip())
            trailing_whitespace = len(raw_chunk) - len(raw_chunk.rstrip())
            trimmed_start = char_start + leading_whitespace
            trimmed_end = char_end - trailing_whitespace
            chunk_text = text[trimmed_start:trimmed_end]
            if chunk_text and estimate_token_count(chunk_text) <= max_tokens:
                break
            end_index -= 1
        if end_index == start_index:
            raise ValueError("max_tokens is too small to encode the next character.")
        if chunk_text:
            chunks.append(
                TextSpan(
                    text=chunk_text,
                    char_start=base_char_start + trimmed_start,
                    char_end=base_char_start + trimmed_end,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
        if end_index == len(token_ids):
            break
        start_index = max(end_index - overlap_tokens, start_index + 1)
    return chunks


def semantic_chunks(
    text: str,
    *,
    max_tokens: int,
    overlap_tokens: int,
    base_char_start: int = 0,
    page_start: int | None = None,
    page_end: int | None = None,
) -> list[TextSpan]:
    spans = paragraph_spans(text)
    chunks: list[TextSpan] = []
    current_spans: list[TextSpan] = []

    for span in spans:
        span_tokens = estimate_token_count(span.text)
        current_tokens = estimate_token_count("\n\n".join(item.text for item in current_spans))
        if current_spans and current_tokens + span_tokens > max_tokens:
            chunks.extend(
                _flush_semantic_chunk(
                    current_spans,
                    base_char_start=base_char_start,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
            current_spans = _overlap_tail(current_spans, overlap_tokens)

        if span_tokens > max_tokens:
            chunks.extend(
                fixed_token_chunks(
                    span.text,
                    max_tokens=max_tokens,
                    overlap_tokens=overlap_tokens,
                    base_char_start=base_char_start + span.char_start,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
            continue

        current_spans.append(span)

    chunks.extend(
        _flush_semantic_chunk(
            current_spans,
            base_char_start=base_char_start,
            page_start=page_start,
            page_end=page_end,
        )
    )
    bounded: list[TextSpan] = []
    for chunk in chunks:
        if estimate_token_count(chunk.text) <= max_tokens:
            bounded.append(chunk)
            continue
        bounded.extend(
            fixed_token_chunks(
                chunk.text,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
                base_char_start=chunk.char_start,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
            )
        )
    return bounded


def summarize_text(text: str, *, max_sentences: int = 3, max_chars: int = 900) -> str:
    cleaned = normalize_document_text(text)
    if len(cleaned) <= max_chars:
        return cleaned

    sentences = split_sentences(cleaned)
    if not sentences:
        return cleaned[:max_chars].rsplit(" ", 1)[0].strip()

    selected: list[str] = []
    for sentence in sentences:
        if not selected or _has_signal(sentence):
            selected.append(sentence)
        if len(selected) >= max_sentences:
            break
    if not selected:
        selected = sentences[:max_sentences]

    summary = " ".join(selected).strip()
    if len(summary) > max_chars:
        summary = summary[:max_chars].rsplit(" ", 1)[0].strip()
    return summary


def shingle_fingerprint(text: str, *, size: int = 5) -> frozenset[str]:
    words = normalize_for_fingerprint(text).split()
    if len(words) < size:
        return frozenset(words)
    return frozenset(
        " ".join(words[index : index + size]) for index in range(len(words) - size + 1)
    )


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def looks_like_boilerplate(text: str) -> bool:
    normalized = normalize_for_fingerprint(text)
    phrases = (
        "forward looking statements",
        "actual results may differ materially",
        "safe harbor",
        "not undertake any obligation to update",
        "all rights reserved",
        "non gaap financial measures",
        "not a solicitation",
    )
    return any(phrase in normalized for phrase in phrases)


def _decode_bytes(content: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _looks_like_html(content_type: str | None, text: str) -> bool:
    if content_type and "html" in content_type.lower():
        return True
    prefix = text[:500].lower()
    return "<html" in prefix or "<document" in prefix or "<sec-document" in prefix


def _has_signal(sentence: str) -> bool:
    normalized = normalize_for_fingerprint(sentence)
    keywords = (
        "revenue",
        "growth",
        "risk",
        "customer",
        "business",
        "management",
        "cash",
        "liquidity",
        "market",
        "competition",
        "operations",
    )
    return any(keyword in normalized for keyword in keywords)


def _flush_semantic_chunk(
    current_spans: list[TextSpan],
    *,
    base_char_start: int,
    page_start: int | None,
    page_end: int | None,
) -> list[TextSpan]:
    if not current_spans:
        return []
    text = "\n\n".join(span.text for span in current_spans).strip()
    if not text:
        return []
    return [
        TextSpan(
            text=text,
            char_start=base_char_start + current_spans[0].char_start,
            char_end=base_char_start + current_spans[-1].char_end,
            page_start=page_start,
            page_end=page_end,
        )
    ]


def _overlap_tail(spans: list[TextSpan], overlap_tokens: int) -> list[TextSpan]:
    if overlap_tokens <= 0:
        return []
    retained: list[TextSpan] = []
    token_total = 0
    for span in reversed(spans):
        retained.append(span)
        token_total += estimate_token_count(span.text)
        if token_total >= overlap_tokens:
            break
    return list(reversed(retained))
