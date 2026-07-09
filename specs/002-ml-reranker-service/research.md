# Phase 0 Research: ML Reranker Service

## Decision: Use a separate reranker service image

**Rationale**: The user explicitly wants ML reranking without making the backend image heavy. A separate service keeps Torch, Transformers, model cache, and model startup costs out of the API/worker image. It also allows local opt-in, separate scaling, and graceful backend fallback when the service is absent.

**Alternatives considered**:

- In-process backend CrossEncoder: simpler call path but bloats the backend image and makes every backend install depend on ML runtime packages.
- Hosted reranker API: avoids local model packaging but adds provider cost, network dependency, data-sharing concerns, and less deterministic local validation.
- Deterministic local scorer: easiest to test but does not satisfy the preference for an ML reranker.

## Decision: Use sentence-transformers CrossEncoder as the first service runtime

**Rationale**: Current sentence-transformers documentation exposes `CrossEncoder.predict()` for scoring query-document pairs and `CrossEncoder.rank()` for ranking documents for one query. It supports batching, device selection, output conversion, activation handling, and `max_length` at model load. This matches the feature need: score one user query against a bounded candidate chunk pool.

**Alternatives considered**:

- Raw Transformers sequence classification pipeline: more control but more boilerplate for tokenization, device placement, batching, and score normalization.
- Embedding-only reranking: cheaper but repeats first-stage similarity style rather than true cross-encoder query-document interaction.
- LLM judge reranking: flexible but slower, less deterministic, more expensive, and harder to keep out of trace payloads.

## Decision: Add `HttpReranker` behind existing `Reranker` protocol

**Rationale**: `RetrievalService` already accepts a `Reranker` and calls `_rerank()` before dedupe/diversity/final top-k selection. Preserving that interface keeps the agent graph unchanged and scopes implementation to retrieval construction, config, diagnostics, and tests.

**Alternatives considered**:

- Call the reranker service from `AdaptiveRetrievalService`: possible, but it bypasses the existing lower-level reranker abstraction and couples adaptive orchestration to a specific provider.
- Add reranking as an agent graph branch: too late in the flow because retrieval result shaping, dedupe, and diversity already belong in retrieval.

## Decision: Default to `noop`, opt into HTTP reranking

**Rationale**: Reranking is an evidence-quality enhancement, not a required dependency for every environment. Default `noop` preserves current behavior, CI stability, and backend startup. HTTP reranking can be enabled in local Docker or evaluation runs.

**Alternatives considered**:

- Enable HTTP reranking by default in dev: useful for discovery, but it would make standard `make start-dev-docker` download and load a model.
- Fail if HTTP reranker is unavailable: useful for strict evaluation only, but poor default product behavior.

## Decision: Support graceful fallback and strict failure modes

**Rationale**: Normal product usage should continue with first-stage retrieval when reranking times out or returns invalid output. Evaluation runs may need fail-closed behavior to prove reranking is actually active. Both modes are required by the spec.

**Alternatives considered**:

- Always fallback: hides misconfigured evaluation runs.
- Always fail: makes optional reranking too fragile for local and demo use.

## Decision: Keep diagnostics privacy-safe and backend-owned

**Rationale**: CompanyLens trace policy forbids raw prompts, raw retrieved passages, provider payloads, credentials, stack traces, and private reasoning in public traces. The backend should record counts, status, model identity, latency, fallback reason, and per-result score/rank, but not chunk text.

**Alternatives considered**:

- Store full reranker request/response for debugging: useful but violates trace and evidence privacy boundaries.
- Hide all reranker diagnostics: safer but undermines evaluation and operator visibility.

## Decision: Test backend with fake HTTP service and service with fake model

**Rationale**: CI should not download model weights or require ML runtime execution. Backend tests can use an in-process fake HTTP handler or test transport. Service unit tests can inject a fake scorer. A manual Docker smoke path covers the real model.

**Alternatives considered**:

- Run the real model in CI: catches packaging issues but makes CI slow, flaky, and dependent on external model downloads.
- Only test pure functions: misses HTTP contract, fallback, and diagnostics behavior.
