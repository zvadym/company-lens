# ADR 0001: Core Domain Hierarchy and Source Lineage

## Status

Accepted

## Context

CompanyLens needs to answer public-company questions from multiple source types: SEC
filings, investor PDFs, XBRL company facts, and macroeconomic observations. Some answers
come from narrative text, while others must come from typed numerical facts. The system
also needs exact citations, hierarchical retrieval, document restatement support, and
repeatable ingestion.

Flat document chunks are not enough because they lose the company, filing, section, page,
and version context required for grounded answers.

## Decision

Use a hierarchical relational model centered on `Company`, `SourceDocument`,
`DocumentVersion`, `FilingSection`, and `DocumentChunk`.

`SourceDocument` stores stable document identity and filing metadata. `DocumentVersion`
stores the ingested content hash, source hash, current/restated state, and the ingestion
run that produced it. This lets re-ingestion identify unchanged content and preserve older
versions.

Narrative retrieval and structured analytics are separated:

- `DocumentSummary`, `SectionSummary`, `DocumentChunk`, and `ChunkEmbedding` support
  text retrieval.
- `FinancialFact` and `MacroObservation` store typed numeric values, periods, units,
  dimensions, and source hashes.

Embeddings are versioned through `EmbeddingIndex`, so the same chunk can be indexed by
multiple embedding models or index versions.

Citations are represented by `EvidenceRecord` and `CitationRecord`. Evidence can point to
a document version, section, chunk, page, financial fact, or macro observation and always
keeps source URL, source ID, and content hash.

## Consequences

The schema supports these retrieval paths:

- start from a filing section and trace back to company, document, source URL, pages, and
  version;
- start from a chunk and expand to its parent section and document;
- compare sections across document versions and reporting periods;
- answer numeric questions from typed facts rather than untyped embedded prose;
- run multiple embedding indexes over the same content.

The schema is larger than a simple `documents` and `chunks` design, but it preserves the
lineage needed for citations, evaluations, and future ingestion checks.
