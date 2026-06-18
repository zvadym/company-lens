# ADR 0003: Exact Entity Resolution And Adaptive Hierarchical Retrieval

## Status

Accepted

## Context

The baseline retrieval service ranks chunks with dense, lexical, or hybrid search. It does
not decide whether a question needs document summaries, detailed passages, structured
financial facts, or no retrieval. Treating every question as chunk search wastes context,
weakens exact-identifier handling, and makes failed recovery difficult to audit.

## Decision

An adaptive orchestration layer is added above the baseline `RetrievalService`. The
baseline service remains the detailed chunk-search primitive.

`EntityResolver` performs deterministic database lookup for company legal/display names,
aliases, tickers, CIKs, company identifiers, and filing accession numbers. Filing forms,
periods, dates, and a provider-neutral registry of known financial metric aliases are
parsed without vector search. Multiple matching companies produce an explicit ambiguous
resolution and stop retrieval rather than selecting a candidate.

`RetrievalPlanner` produces a validated `RetrievalPlan` with one of six strategies:
`none`, `summary_only`, `section_level`, `detailed`, `structured_only`, or `hybrid`.
The plan contains exact metadata filters, document/section/chunk/token limits, per-company
and per-period limits, and a bounded attempt count. Comparative questions receive larger
budgets than simple lookups.

Detailed and hybrid retrieval assemble evidence in hierarchical order: document summaries,
section summaries, structured facts when requested, then source chunks. Every evidence
item carries its citation label, source URL, source ID, and available document, section,
chunk, page, company, and period lineage. Budget compression shortens content without
removing that citation metadata.

Evidence recovery follows a finite strategy sequence. Each retry changes strategy, records
its reason and resulting context size, and stops after the plan's maximum attempts. Exact
identifier ambiguity and missing exact filing identifiers abstain before semantic search.

## Consequences

Callers can inspect a deterministic evidence package and complete retrieval trace through
the Python service or `company-lens adaptive-retrieve`. This issue does not generate a
natural-language answer; answer synthesis and claim validation remain responsibilities of
the later agent and evidence layers.

The financial metric registry resolves common concepts already present in
`financial_facts`. Broad SEC Company Facts ingestion and taxonomy normalization remain in
the structured-data milestone.
