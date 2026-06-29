from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _looks_ukrainian(text: str) -> bool:
    normalized = text.casefold()
    return any(
        token in normalized
        for token in (
            "граф",
            "період",
            "скільки",
            "репорт",
            "тепер",
            "те саме",
            "для ",
            "поперед",
            "компан",
            "і",
            "ї",
            "є",
            "ґ",
        )
    )


def _resolve_extracted_company_mentions(
    state: AgentState,
    runtime: Runtime[ResearchAgentRuntime],
    resolved: ResolvedQuery,
    analysis: QuestionAnalysis | None,
) -> ResolvedQuery:
    if not _should_extract_company_mentions(analysis):
        return resolved
    base_resolved = _resolved_query_without_company_entities(resolved)
    messages = (
        ModelMessage(
            role="system",
            content=(
                "Extract public-company names or stock tickers explicitly present in the current "
                "user message. You may include candidate ticker, CIK, or legal-name hints for "
                "well-known public-company aliases, but those fields are verification hints only. "
                "Do not use prior conversation context, and do not add companies that are only "
                "implied. Do not return ordinary words, metrics, products, chart types, or "
                "visualization words such as bar, line, area, scatter, table, chart, graph, plot, "
                "revenue, growth, cash, or rate unless they are clearly being used as a company "
                "name or stock ticker. Use English lowercase_snake_case reason codes."
            ),
        ),
        ModelMessage(
            role="user",
            content=(
                f"Current user message: {state['question']}\n"
                f"Normalized question: {_normalized_analysis_question(state, analysis)}\n"
                f"Route: {analysis.route if analysis else 'unknown'}\n"
                "Return only company candidates from the current user message."
            ),
        ),
    )
    extraction, _attempts, error = _generate_structured_with_retries(
        runtime.context.model_provider,
        messages,
        CompanyMentionExtraction,
        purpose=ModelPurpose.ENTITY_EXTRACTION,
        max_retries=state["policy"].max_retries_per_node,
        node="resolve_entities",
    )
    if error is not None or extraction is None:
        return base_resolved
    companies = _explicit_company_mentions_from_extraction(state["question"], extraction.companies)
    if not companies:
        return base_resolved
    resolved_entities = runtime.context.tools.resolve_public_company_mentions(companies)
    if resolved_entities:
        return _resolved_query_with_extra_entities(base_resolved, resolved_entities)
    unresolved_mentions = tuple(
        EntityResolution(kind="public_company", mention=company.mention, status="unresolved")
        for company in companies
    )
    return _resolved_query_with_extra_entities(base_resolved, unresolved_mentions)


def _explicit_company_mentions_from_extraction(
    question: str,
    candidates: tuple[CompanyMentionCandidate, ...],
) -> tuple[CompanyMentionCandidate, ...]:
    explicit: list[CompanyMentionCandidate] = []
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    for candidate in candidates:
        mention = _explicit_company_mention(question, candidate)
        if mention is None:
            continue
        normalized = candidate.model_copy(update={"mention": mention})
        key = (
            normalized.mention.casefold(),
            normalized.ticker,
            normalized.cik,
            normalized.legal_name.casefold() if normalized.legal_name else None,
        )
        if key in seen:
            continue
        seen.add(key)
        explicit.append(normalized)
    return tuple(explicit)


def _explicit_company_mention(
    question: str,
    candidate: CompanyMentionCandidate,
) -> str | None:
    if _phrase_in_question(question, candidate.mention):
        return candidate.mention
    if candidate.ticker is not None and _ticker_in_question(question, candidate.ticker):
        return candidate.ticker
    for value in (candidate.legal_name, candidate.mention):
        if value is None:
            continue
        prefix = _explicit_prefix_in_question(question, value)
        if prefix is not None:
            return prefix
    return None


def _phrase_in_question(question: str, phrase: str) -> bool:
    normalized_phrase = _normalized_company_phrase(phrase)
    if not normalized_phrase:
        return False
    normalized_question = f" {_normalized_company_phrase(question)} "
    return f" {normalized_phrase} " in normalized_question


def _ticker_in_question(question: str, ticker: str) -> bool:
    normalized_ticker = ticker.strip().upper().removeprefix("$")
    if not normalized_ticker:
        return False
    if len(normalized_ticker) == 1:
        return bool(
            re.search(
                rf"(?<![A-Za-z0-9])\${re.escape(normalized_ticker)}(?![A-Za-z0-9])",
                question,
                flags=re.IGNORECASE,
            )
        )
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9])\$?{re.escape(normalized_ticker)}(?![A-Za-z0-9])",
            question,
            flags=re.IGNORECASE,
        )
    )


def _explicit_prefix_in_question(question: str, value: str) -> str | None:
    raw_tokens = re.findall(r"\w+", value)
    normalized_tokens = [_normalized_company_phrase(token) for token in raw_tokens]
    if not normalized_tokens:
        return None
    for length in range(min(len(normalized_tokens), 4), 0, -1):
        prefix = " ".join(normalized_tokens[:length])
        if prefix in _EXPLICIT_COMPANY_PREFIX_STOPWORDS:
            continue
        if _phrase_in_question(question, prefix):
            return " ".join(raw_tokens[:length])
    return None


def _normalized_company_phrase(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


_EXPLICIT_COMPANY_PREFIX_STOPWORDS = {
    "a",
    "an",
    "and",
    "company",
    "corp",
    "corporation",
    "inc",
    "llc",
    "ltd",
    "the",
}


__all__ = (
    "_looks_ukrainian",
    "_resolve_extracted_company_mentions",
    "_explicit_company_mentions_from_extraction",
    "_explicit_company_mention",
    "_phrase_in_question",
    "_ticker_in_question",
    "_explicit_prefix_in_question",
    "_normalized_company_phrase",
    "_EXPLICIT_COMPANY_PREFIX_STOPWORDS",
)
