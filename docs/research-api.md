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
event uses schema version `1` and a monotonically increasing numeric ID. Browsers reconnect with
the standard `Last-Event-ID` header; the server replays only events with a greater ID. Heartbeat
comments keep idle connections alive, and the stream closes after the terminal event is delivered.

```text
id: 42
event: node.status
data: {"id":42,"schema_version":"1","run_id":"...","type":"node.status","occurred_at":"...","data":{"node":"query_financial_facts","status":"completed","duration_ms":184,"summary":"Financial facts loaded."}}
```

Public event types are:

- `run.status`: queue and execution lifecycle transitions.
- `node.status`: safe node status, duration, and summary; never prompts or hidden reasoning.
- `tool.call`: branch kind, public status, attempts, and an optional typed error code.
- `retrieval.summary`: branch ID and retrieved passage count.
- `chart.ready`: validated chart type and title.
- `answer.token`: deterministic chunks emitted only from the final citation-validated or repaired
  answer. Draft model output is never streamed.
- `run.terminal`: final public state and optional public error code.

The SSE envelope is documented here because OpenAPI does not describe an unbounded event sequence;
all HTTP request and response models remain available in `/openapi.json`.

## Supporting endpoints

- `GET /api/v1/research/{run_id}` returns lifecycle metadata and the completed result.
- `GET /api/v1/research/{run_id}/sources` returns hydrated source previews.
- `POST /api/v1/feedback` stores a positive or negative run rating and optional comment.
- `GET /api/v1/companies` lists companies and active primary tickers.

Demo mode uses an anonymous principal. `X-Client-ID` provides a stable anonymous boundary for rate
limits; otherwise the client IP is hashed before it is used as the PostgreSQL bucket key. Future
authentication can replace the FastAPI principal dependency without changing route contracts.

Errors always use `{ "error": { "code", "message", "correlation_id" } }`. Validation details,
provider exceptions, SQL errors, and stack traces are not public.
