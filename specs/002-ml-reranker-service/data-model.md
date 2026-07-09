# Data Model: ML Reranker Service

## RerankProvider

Represents the backend-selected reranking mode.

Fields:

- `provider`: `noop` or `http`.
- `name`: Human-readable provider name used in diagnostics.
- `fail_closed`: Whether provider failure should abort retrieval instead of falling back.

Validation rules:

- `noop` never requires a URL.
- `http` requires a non-empty service URL.
- `fail_closed` defaults to false.

## RerankCandidate

Represents a document retrieval candidate submitted for second-stage scoring.

Fields:

- `id`: Opaque string candidate ID. For backend retrieval this is the chunk UUID string.
- `query`: User retrieval query, supplied once per request.
- `text`: Candidate chunk text used for model scoring.
- `original_score`: First-stage retrieval score used for fallback ordering.

Relationships:

- Maps to an existing `DocumentChunk` through the opaque candidate ID.
- Source lineage remains backend-owned and is not sent back by the service.

Validation rules:

- `id` must be non-empty and unique within one request.
- `text` must be non-empty after stripping.
- Candidate count must not exceed backend candidate limits.

## RerankRequest

Represents one batch scoring request from backend to reranker service.

Fields:

- `query`: Non-empty user retrieval query.
- `items`: Ordered list of `RerankCandidate` payload entries containing `id` and `text`.

Validation rules:

- `query` must be non-empty.
- `items` may be empty only if first-stage retrieval produced no candidates; backend should normally skip the call in that case.
- Request payload size must be bounded by service limits.

## RerankScore

Represents one model score returned by the reranker service.

Fields:

- `id`: Candidate ID echoed from the request.
- `score`: Numeric relevance score where larger means more relevant.

Validation rules:

- `id` must match a submitted candidate ID.
- `score` must be finite.
- Duplicate IDs are invalid for strict mode and ignored with diagnostics for graceful fallback.

## RerankResponse

Represents the service result for one request.

Fields:

- `model`: Model identity used by the service.
- `scores`: List of `RerankScore`.

Validation rules:

- `model` must be non-empty when scoring succeeds.
- Each response score must map to at most one submitted candidate.
- Missing candidate scores are treated as partial scoring.

## RerankDiagnostics

Represents privacy-safe backend diagnostics for one retrieval operation.

Fields:

- `provider`: Selected provider.
- `status`: `disabled`, `succeeded`, `partial`, `fallback`, or `failed`.
- `model`: Model identity when available.
- `candidate_count`: Count of candidates considered for reranking.
- `scored_count`: Count of candidates with accepted reranker scores.
- `latency_ms`: Reranker call duration.
- `fallback_reason`: Sanitized reason when fallback occurs.
- `warnings`: Bounded warning codes.

Validation rules:

- Must not include raw chunk text, raw request payloads, provider exception strings, credentials, or stack traces.
- `scored_count` cannot exceed `candidate_count`.

## RetrievalResult Extensions

Existing retrieval results already expose `scores.reranker_score` and `diagnostics.reranker_rank`.
This feature uses those fields and extends response-level diagnostics.

State transitions:

```text
disabled -> first-stage ordering
succeeded -> reranker score ordering
partial -> scored candidates first, unscored candidates retain fallback score with diagnostics
fallback -> first-stage ordering with fallback diagnostics
failed -> retrieval error only when strict failure mode is enabled
```
