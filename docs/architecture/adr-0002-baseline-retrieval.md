# ADR 0002: Baseline Dense, Lexical, And Hybrid Retrieval

## Status

Accepted

## Context

CompanyLens needs a first production-oriented retrieval layer over the hierarchical
document model created by ingestion and processing. Retrieval must preserve source
lineage, support exact metadata filters, and remain runnable locally without external
model credentials.

## Decision

The baseline retrieval unit is `DocumentChunk`. Dense, lexical, and hybrid modes rank
chunks first, then attach parent section, document, company, filing, period, page, and
source metadata. Section and document summaries are optional expansion text, not primary
ranked units in this version.

Dense retrieval uses a deterministic local feature-hashing embedding backend with 384
dimensions and versioned `EmbeddingIndex` records. This gives repeatable local tests and
keeps the provider replaceable. Embeddings are rebuilt only when missing, forced, or stale
against the current chunk `content_hash`.

Lexical retrieval uses PostgreSQL full-text search over a generated `tsvector` column on
`document_chunks`, queried with `websearch_to_tsquery('english', query)`. Dense PostgreSQL
retrieval uses pgvector cosine distance with an HNSW index. SQLite is used only as a unit
test and benchmark fallback.

Hybrid retrieval uses Reciprocal Rank Fusion over independent dense and lexical candidate
lists, avoiding score-scale coupling. A replaceable reranker interface is present, with a
default no-op implementation that records deterministic diagnostics.

Result shaping applies exact filters before ranking, removes exact and near-duplicate
chunks using content hashes plus shingle/Jaccard similarity, and applies soft diversity
caps across documents and fiscal periods. If dense embeddings are missing, dense mode
returns no results with diagnostics; hybrid mode continues with lexical candidates and
records the missing dense branch.

## Consequences

The baseline is deterministic, locally runnable, and easy to benchmark. It does not add a
FastAPI retrieval endpoint or external embedding provider; those remain replaceable
integration points for later product and model work.
