# Research API and SSE

The versioned API exposes durable research runs under `/api/v1`. PostgreSQL is the source of
truth for the queue, results, events, feedback, cancellation, and worker leases. API processes do
not execute research inline; run `company-lens research-worker` as a separate service.

## Lifecycle

`POST /api/v1/research` returns `202 Accepted` with a generated `run_id` and, when omitted by the
caller, a generated `session_id`. A session can have only one run in `queued`, `running`, or
`cancellation_requested`. Terminal states are `completed`, `partial`, `abstained`, `failed`,
`cancelled`, and `timed_out`.

Workers claim rows with `FOR UPDATE SKIP LOCKED` and a renewable lease. After a worker restart, a
pending LangGraph checkpoint is resumed; a terminal checkpoint is materialized without rerunning;
and a run without a checkpoint starts with its original ID. Cancellation is cooperative and is
checked between bounded graph steps. `DELETE /api/v1/research/{run_id}` is idempotent.

## Event stream

Connect to `GET /api/v1/research/{run_id}/events` with `Accept: text/event-stream`. Every persisted
event has a monotonically increasing numeric ID. New workers write schema version `2`; existing
version `1` rows remain replayable without migration. Browsers reconnect with the standard
`Last-Event-ID` header. A client recovering after a page reload can also pass `after_id`. When both
are present, the server uses the larger cursor and replays only newer events. Heartbeat comments
keep idle connections alive, and the stream closes after the terminal event is delivered.

```text
id: 42
event: node.status
data: {"id":42,"schema_version":"2","run_id":"...","type":"node.status","occurred_at":"...","data":{"step_id":"...","node":"query_financial_facts","branch_id":"facts","status":"completed","attempt":1,"summary":"Branch execution completed.","duration_ms":184}}
```

Version `2` payloads are Pydantic models rather than arbitrary dictionaries:

| Event | Public data |
|---|---|
| `run.status` | Queue and execution lifecycle status. |
| `analysis.summary` | Route, required capabilities, follow-up/chart flags, and reason codes. |
| `entities.summary` | Resolved, ambiguous, or unresolved entities plus normalized public filters. |
| `plan.summary` | Route, citation requirement, branch dependency graph, and sanitized requests. |
| `node.status` | Stable step ID, node, optional branch, start/final status, attempt, summary, duration. |
| `tool.status` | Branch status, attempts, cache use, duration, result counts, formula, warnings, error code. |
| `validation.summary` | Claim/support/issue counts, reason codes, semantic-check counts, repair attempt. |
| `chart.ready` | Validated chart type/title and bounded series, point, and source counts. |
| `answer.token` | Deterministic chunks from the final citation-validated or repaired answer. |
| `run.terminal` | Final public state and optional public error code. |

`tool.status.result` is discriminated by branch kind. Retrieval results expose strategy, adaptive
attempt summaries, evidence count, context-token count, and abstention. Financial and macro tools
expose observation/series counts, units or metrics, and bounded warnings. Calculations expose the
deterministic operation, formula, unit, and output/source counts. Full datasets remain available
only through validated final artifacts and evidence APIs.

### Trace privacy boundary

The execution trace explains what the system did, not the model's private reasoning. The public
projector reads validated agent state and emits an explicit allowlist of fields. It never includes:

- system or provider prompts, conversation payloads, or hidden chain-of-thought;
- raw retrieved passages, document contents, or unrestricted tool responses;
- draft or citation-invalid answers;
- provider request/response bodies, credentials, exception strings, or stack traces.

Node and tool summaries are deterministic application text. Reason codes, typed arguments, counts,
formulas, lineage metadata, retries, and validation outcomes provide the educational explanation.

The SSE envelope is documented here because OpenAPI does not describe an unbounded event sequence;
all HTTP request and response models remain available in `/openapi.json`.

## Supporting endpoints

- `GET /api/v1/research?session_id=...&limit=50` returns the latest runs for a session in
  chronological order. `total` reports the complete session count; an unknown session is empty.
- `GET /api/v1/research/{run_id}` returns lifecycle metadata and the completed result.
- `GET /api/v1/research/{run_id}/sources` returns hydrated source previews.
- `POST /api/v1/feedback` stores a positive or negative run rating and optional comment.
- `GET /api/v1/companies` lists companies and active primary tickers.

Demo mode uses an anonymous principal. `X-Client-ID` provides a stable anonymous boundary for rate
limits; otherwise the client IP is hashed before it is used as the PostgreSQL bucket key. Future
authentication can replace the FastAPI principal dependency without changing route contracts.

Errors always use `{ "error": { "code", "message", "correlation_id" } }`. Validation details,
provider exceptions, SQL errors, and stack traces are not public.
