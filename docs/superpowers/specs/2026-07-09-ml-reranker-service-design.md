# ML Reranker Service Design

## Status

Design approved for issue #61. Implementation has not started.

## Context

CompanyLens document retrieval already collects a candidate pool through dense, lexical, or hybrid
search. `RetrievalService` then calls the existing `Reranker` protocol before dedupe, diversity, and
final `top_k` selection. The default implementation is `NoopReranker`, so candidate order is still
driven by the first-stage retrieval score.

Issue #61 adds a real second-stage relevance scorer for `query + chunk` pairs. The user preference is
to use an ML reranker, but keep the backend image slim by packaging ML dependencies in a separate
service image.

## Goals

- Add a production-shaped external reranker integration without adding Torch or Transformers to the
  backend image.
- Preserve `NoopReranker` as the default and safe fallback.
- Score first-stage retrieval candidates in batches before final evidence selection.
- Keep exact metadata filters, lineage, citations, dedupe, and diversity behavior unchanged.
- Record diagnostics that explain reranker usage, score, rank, model identity, and fallback status.
- Make local development possible through Docker Compose while keeping unit tests independent of the
  real ML model.

## Non-Goals

- Do not implement query rewriting or multi-query retrieval. That belongs to issue #62 and depends on
  reranking.
- Do not make the reranker service part of the public API.
- Do not require GPU support in the first implementation.
- Do not block CI on downloading or running a real ML model.
- Do not remove the existing local deterministic embedding or retrieval paths.

## Architecture

The backend keeps the existing `Reranker` protocol:

```text
RetrievalService
  -> first-stage dense / lexical / hybrid candidates
  -> Reranker.rerank(query + candidate text)
  -> sort by reranker score
  -> dedupe and diversity
  -> final top_k evidence
```

Add one backend adapter:

- `NoopReranker`: current fallback and default.
- `HttpReranker`: calls an internal reranker service over HTTP.

Add one separate service:

- `reranker`: a Python image containing ML dependencies and a small HTTP API.
- The service lazy-loads a configured cross-encoder reranker model.
- It scores candidate pairs in batches and returns model scores by candidate ID.

The first target model should be configurable. A reasonable default for local experiments is a
cross-encoder style reranker such as `BAAI/bge-reranker-base`, but the exact model remains a runtime
configuration value so deployments can choose a smaller or larger model without code changes.

## Backend Configuration

Add settings with conservative defaults:

```dotenv
COMPANY_LENS_RERANKER_PROVIDER=noop
COMPANY_LENS_RERANKER_URL=http://reranker:8080
COMPANY_LENS_RERANKER_TIMEOUT_SECONDS=2
COMPANY_LENS_RERANKER_FAIL_CLOSED=false
```

Provider behavior:

- `noop`: use `NoopReranker`.
- `http`: use `HttpReranker`.

Failure behavior:

- If `COMPANY_LENS_RERANKER_FAIL_CLOSED=false`, HTTP errors, timeouts, invalid responses, or service
  unavailability fall back to original candidate scores and emit diagnostics.
- If `COMPANY_LENS_RERANKER_FAIL_CLOSED=true`, reranker failures raise an internal retrieval error.
  This mode is useful only for controlled evaluation and should not be the default.

## Reranker API

The service exposes an internal endpoint:

```http
POST /rerank
```

Request:

```json
{
  "query": "What risks did Cloudflare report in its 2025 10-K?",
  "items": [
    { "id": "chunk-1", "text": "Risk Factors ..." },
    { "id": "chunk-2", "text": "Revenue increased ..." }
  ]
}
```

Response:

```json
{
  "model": "BAAI/bge-reranker-base",
  "scores": [
    { "id": "chunk-1", "score": 0.91 },
    { "id": "chunk-2", "score": 0.12 }
  ]
}
```

API rules:

- Item IDs are opaque strings and must be echoed exactly.
- Scores are floats where larger means more relevant.
- Missing item IDs are treated as unscored and retain the original retrieval score only when fallback
  mode is enabled.
- Extra response IDs are ignored and recorded as diagnostics.
- Request and response sizes are bounded by backend candidate limits and service payload limits.

## Reranker Service Runtime

The first implementation should be a minimal internal HTTP service:

- Python application, likely FastAPI or a small ASGI app.
- ML dependencies live only in the reranker image.
- Model name, cache directory, batch size, max sequence length, and device are environment
  configurable.
- Model loading is lazy or startup-based with a clear readiness signal.
- CPU is supported by default; GPU can be added later through deployment configuration.

Suggested service configuration:

```dotenv
COMPANY_LENS_RERANKER_MODEL=BAAI/bge-reranker-base
COMPANY_LENS_RERANKER_BATCH_SIZE=16
COMPANY_LENS_RERANKER_MAX_LENGTH=512
COMPANY_LENS_RERANKER_DEVICE=cpu
```

## Docker And Local Development

Add a separate reranker image, for example `Dockerfile.reranker`.

Add a Docker Compose service:

```text
reranker
  -> builds Dockerfile.reranker
  -> exposes only the internal compose network port
  -> stores model cache in a named volume
```

Development should remain usable without the reranker:

- Existing `make start-dev-docker` can keep `COMPANY_LENS_RERANKER_PROVIDER=noop` by default.
- Enabling the service can be a documented environment override, or a compose profile if that better
  matches the current Docker setup.
- The backend must not fail startup when the reranker service is absent unless provider `http` is
  explicitly selected with fail-closed behavior.

## Diagnostics And Observability

Retrieval responses already expose reranker diagnostics. Extend them so a run can show:

- reranker provider and name;
- model name when available;
- candidate count sent to the reranker;
- scored count;
- timeout or fallback reason;
- reranker latency in milliseconds;
- per-result `reranker_score` and `reranker_rank`.

OpenTelemetry instrumentation should wrap the HTTP call with sanitized metadata only:

- candidate count;
- model name;
- latency;
- status;
- fallback reason.

Do not attach chunk text, prompts, or full request payloads to traces.

## Error Handling

The backend `HttpReranker` handles:

- connection errors;
- timeouts;
- non-2xx responses;
- invalid JSON;
- schema-invalid scores;
- partial missing scores;
- duplicate score IDs.

Default user-facing behavior remains graceful degradation. Retrieval continues with first-stage
ordering and emits diagnostics. Internal logs and spans carry the failure reason without leaking
document text.

The reranker service should reject oversized payloads and return typed 4xx errors for malformed
requests. Model inference exceptions return a sanitized 500 response.

## Testing

Backend unit tests:

- `HttpReranker` sends the expected payload and maps response scores.
- Candidate ordering changes when the fake HTTP service returns new scores.
- Fallback to `NoopReranker` behavior occurs on timeout, invalid response, missing scores, and
  service errors.
- Fail-closed mode raises a typed error.
- Retrieval diagnostics include provider, candidate counts, scores, ranks, and fallback reason.

Service unit tests:

- Request validation accepts valid payloads and rejects malformed or oversized requests.
- The scoring path can be tested with a fake model object so CI does not download the real model.
- Batching preserves item IDs and output order does not matter.

Integration or manual smoke test:

- Docker Compose can start the reranker service.
- Backend with `COMPANY_LENS_RERANKER_PROVIDER=http` can retrieve documents and receive non-noop
  reranker scores.
- A manual benchmark compares hybrid retrieval with and without the HTTP reranker on the golden
  retrieval slice.

## Rollout Plan

1. Add backend config and `HttpReranker` with fake-service tests.
2. Wire reranker construction into the existing application/retrieval service factory.
3. Add diagnostics and observability around reranker calls.
4. Add the reranker service and separate image.
5. Add Docker Compose support and local documentation.
6. Add a manual smoke test or benchmark path using a real model.

The default remains `noop` until model choice, latency, and retrieval quality are evaluated.

## Scope Boundaries For Implementation

This slice is complete when issue #61 can use a non-noop external ML reranker in local Docker
development and backend tests prove ordering, diagnostics, and fallback behavior. It does not need
to prove that a specific model improves every golden case; it only needs to provide the correct
integration and a benchmark path for measuring quality.

## Spec Self-Review

- Placeholder scan: no TBD or TODO sections remain.
- Internal consistency: the backend owns retrieval orchestration; the separate service owns ML
  dependencies and scoring.
- Scope check: the slice is focused on issue #61 and explicitly excludes issue #62 query rewriting.
- Ambiguity check: fallback, fail-closed behavior, API shape, diagnostics, and test boundaries are
  specified.
