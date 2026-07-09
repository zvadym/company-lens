# Backend Reranker Configuration Contract

## Settings

| Setting | Values | Default | Required When | Purpose |
|---|---|---:|---|---|
| `COMPANY_LENS_RERANKER_PROVIDER` | `noop`, `http` | `noop` | Always | Selects reranker provider. |
| `COMPANY_LENS_RERANKER_URL` | Absolute HTTP URL | `http://reranker:8080` | provider is `http` | Internal reranker service base URL. |
| `COMPANY_LENS_RERANKER_TIMEOUT_SECONDS` | Float > 0 | `2.0` | provider is `http` | Bounds one reranker request. |
| `COMPANY_LENS_RERANKER_FAIL_CLOSED` | `true`, `false` | `false` | Always | Controls fallback vs retrieval failure on provider errors. |

## Provider Semantics

- `noop`: preserve current first-stage ordering and record disabled/noop diagnostics.
- `http`: send bounded candidate batch to the internal reranker service and apply accepted scores.

## Failure Semantics

Graceful fallback mode:

- Triggered when `COMPANY_LENS_RERANKER_FAIL_CLOSED=false`.
- Connection failures, timeouts, non-2xx responses, invalid JSON, schema-invalid scores, and partial missing scores do not fail the retrieval operation.
- Retrieval continues with first-stage ordering or partial accepted scores, and response diagnostics record sanitized warning codes.

Strict mode:

- Triggered when `COMPANY_LENS_RERANKER_FAIL_CLOSED=true`.
- Reranker provider failure raises a typed retrieval error.
- Public errors must remain sanitized and must not include provider exception strings or raw payloads.

## Diagnostics Contract

Response-level retrieval diagnostics should include:

- `reranker_provider`
- `reranker_name`
- `reranker_model`
- `reranker_status`
- `reranker_candidate_count`
- `reranker_scored_count`
- `reranker_latency_ms`
- `reranker_fallback_reason`

Per-result fields should continue to use:

- `scores.reranker_score`
- `diagnostics.reranker_rank`

Diagnostics must not include raw chunk text, raw reranker request/response bodies, credentials, stack traces, or hidden reasoning.
