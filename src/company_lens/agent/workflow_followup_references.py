from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _references_multiple_prior_companies(question: str) -> bool:
    normalized = question.casefold()
    markers = (
        "them",
        "both",
        "their",
        "these companies",
        "those companies",
        "both companies",
        "the companies",
        "these two",
        "ці компан",
        "цих компан",
        "обидві компан",
        "обидва компан",
        "эти компан",
        "обе компан",
    )
    return any(_contains_reference_term(normalized, marker) for marker in markers)


def _mentions_multiple_recent_companies(question: str, memory: SessionMemory) -> bool:
    normalized = question.casefold()
    matched_company_ids: set[uuid.UUID | str] = set()
    for query in memory.recent_resolved_queries:
        for entity in query.entities:
            if entity.kind not in {"company", "public_company"}:
                continue
            if any(
                _contains_reference_term(normalized, term)
                for term in _company_reference_terms(entity)
            ):
                matched_company_ids.add(_company_identity(entity))
    return len(matched_company_ids) >= 2


def _company_reference_terms(entity: EntityResolution) -> tuple[str, ...]:
    values: list[str] = [entity.mention]
    if entity.canonical_value is not None:
        values.append(entity.canonical_value)
    values.extend(candidate.display_value for candidate in entity.candidates)
    values.extend(candidate.canonical_value for candidate in entity.candidates)
    terms: list[str] = []
    for value in values:
        term = _clean_company_reference_term(value)
        if term is None:
            continue
        terms.append(term)
        if "," in term:
            terms.append(term.split(",", 1)[0].strip())
    return tuple(dict.fromkeys(term for term in terms if term))


def _clean_company_reference_term(value: str | None) -> str | None:
    if value is None:
        return None
    term = " ".join(value.casefold().replace(".", "").split())
    if not term:
        return None
    with suppress(ValueError):
        uuid.UUID(term)
        return None
    if term.isascii() and len(term) < 4:
        return None
    return term


def _company_identity(entity: EntityResolution) -> uuid.UUID | str:
    for candidate in entity.candidates:
        if candidate.id is not None:
            return candidate.id
    values = (
        entity.canonical_value,
        *(candidate.canonical_value for candidate in entity.candidates),
    )
    for value in values:
        if value is None:
            continue
        with suppress(ValueError):
            return uuid.UUID(value)
    return entity.mention.casefold()


def _contains_reference_term(text: str, term: str) -> bool:
    normalized_term = term.casefold().strip()
    if not normalized_term:
        return False
    if normalized_term.isascii() and normalized_term.replace(" ", "").isalnum():
        pattern = rf"(?<![a-z0-9_]){re.escape(normalized_term)}(?![a-z0-9_])"
        return re.search(pattern, text) is not None
    return normalized_term in text


__all__ = (
    "_references_multiple_prior_companies",
    "_mentions_multiple_recent_companies",
    "_company_reference_terms",
    "_clean_company_reference_term",
    "_company_identity",
    "_contains_reference_term",
)  # noqa: E501
