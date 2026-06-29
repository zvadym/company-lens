# Observability, reliability, and security operations

This runbook describes the controls implemented for CompanyLens research and ingestion workloads.

## Observability

CompanyLens uses OpenTelemetry as the instrumentation boundary. Langfuse is the primary trace
backend; Prometheus-format metrics are exposed at `GET /metrics`. By default, telemetry records
metadata, timing, status, model identity, and token usage, but does not attach prompts, document
contents, model outputs, API keys, or database credentials to spans.

Configure Langfuse with deployment-managed secrets:

```dotenv
COMPANY_LENS_TELEMETRY_ENABLED=true
COMPANY_LENS_METRICS_ENABLED=true
COMPANY_LENS_TRACE_CONTENT=metadata
COMPANY_LENS_LANGFUSE_PUBLIC_KEY=pk-lf-...
COMPANY_LENS_LANGFUSE_SECRET_KEY=sk-lf-...
COMPANY_LENS_LANGFUSE_BASE_URL=https://cloud.langfuse.com
COMPANY_LENS_SERVICE_VERSION=<git-sha-or-release>
COMPANY_LENS_PROMPT_VERSION=research-v1
COMPANY_LENS_PARSER_VERSION=document-parser-v1
```

`COMPANY_LENS_TRACE_CONTENT` controls whether Langfuse generation observations include raw
input/output payloads:

| Value | Behavior | Recommended use |
|---|---|---|
| `metadata` | Records model, purpose, latency, status, and token usage only. No prompts or outputs are attached. | Default for all environments |
| `redacted` | Records truncated previews with obvious secrets redacted. | Local debugging or controlled staging |
| `full` | Records full prompt and model output payloads. | Local-only debugging with non-sensitive data |

Do not use `full` in production unless the deployment has an explicit data-retention and access
review for prompts, retrieved evidence, user questions, and generated answers.

One research request is correlated through:

```text
X-Request-ID → research_runs.correlation_id → research run_id
  → worker span → LangGraph node spans → model/tool/external-service spans → SQL spans
```

Every structured log includes `correlation_id`, `run_id`, and `session_id` when available. Relevant
metrics include:

- `company_lens_operation_count_total` by operation, kind, and status;
- `company_lens_operation_duration_milliseconds` for API, node, tool, and provider latency;
- `company_lens_model_tokens_total` by model, purpose, and direction;
- `company_lens_model_cost_USD_total` when an explicit cost is supplied.

Langfuse Sessions use the CompanyLens research `session_id`. To inspect a multi-turn research,
open Langfuse Sessions and filter for the API response `session_id`. Each trace also carries
`run_id` and `correlation_id` metadata so a specific API response or worker log line can be matched
back to the grouped Langfuse session. The same values remain available as `company_lens.*` span
attributes for OpenTelemetry backends that do not understand Langfuse session metadata.

Langfuse derives model cost from the model and `gen_ai.usage.*` span attributes when its model
catalog contains the selected model. Pin and emit service, prompt, parser, embedding, and index
versions for every deployment so traces remain reproducible.

## Reliability policy

External clients use explicit request timeouts, bounded retries, exponential backoff with jitter,
and per-client circuit breakers. Only connection errors, timeouts, HTTP 429, and HTTP 5xx responses
are retryable. Validation, authentication, and other HTTP 4xx failures fail immediately.

| Dependency | Timeout | Retry owner | Circuit breaker | Degraded result |
|---|---:|---|---|---|
| SEC | `SEC_REQUEST_TIMEOUT_SECONDS` | shared retry policy | yes | ingestion failure is recorded |
| Investor PDF | `INVESTOR_PDF_REQUEST_TIMEOUT_SECONDS` | shared retry policy | yes | document failure is recorded |
| FRED | `FRED_REQUEST_TIMEOUT_SECONDS` | shared retry policy | yes | macro branch may become partial |
| OpenAI model | purpose-specific timeout | LangGraph workflow | yes | repair, partial result, or abstention |
| OpenAI embeddings | embedding timeout | shared retry policy | yes | indexing batch fails without partial write |

Ingestion uses stable source identities, hashes, uniqueness constraints, and transactions so a
repeated command updates or reuses existing records rather than duplicating them. Research state is
checkpointed in PostgreSQL. A worker that receives the same run resumes pending nodes and does not
repeat completed tool calls.

### Cache policy

- Research-session source results are bounded by `AGENT_SESSION_MAX_CACHED_RESULTS` and expire with
  the research session TTL.
- Cached results are reusable only when their typed request fingerprint matches.
- Retrieval results carry index and embedding versions; a version change is a cache boundary.
- External ingestion data is durable source data, not an HTTP response cache. Refreshes remain
  idempotent and preserve source lineage.
- Rate limits are durable PostgreSQL buckets. HTTP 429 responses include `Retry-After`.

## Failure response

1. Locate the trace using `run_id` from the API response or `X-Request-ID` from the response header.
2. Identify the first error span, then check retry attempts and circuit state for that provider.
3. Confirm the run deadline and cancellation state before restarting a worker.
4. For a stopped worker, start another worker. Its lease claim and LangGraph checkpoint resume the
   run safely.
5. For repeated external failures, leave the circuit open, verify provider status and credentials,
   then wait for the recovery interval. Do not increase retries without a latency-budget review.
6. For terminal parsing or validation errors, preserve the failed artifact and run ID, correct the
   parser or mapping, and rerun the idempotent ingestion command.

Public failures must use typed, sanitized errors. Never return raw provider exceptions, request
URLs containing query secrets, prompts, database errors, or stack traces to API clients.

## Security controls

- Secrets enter through environment variables or the deployment secret manager and are represented
  as `SecretStr` in settings where application code must access them.
- SEC, FRED, and investor-document clients enforce HTTPS host allowlists. Redirect destinations are
  validated before being requested; credentials and private IP destinations are rejected.
- API bodies, questions, comments, SEC responses, and PDFs have explicit size limits.
- HTML extraction discards scripts, styles, templates, SVG, and non-rendered content.
- Retrieved document text is labelled `untrusted_external_data`, sanitized, checked for common
  prompt-injection patterns, and placed behind a system instruction that forbids executing document
  instructions.
- Model spans do not capture raw prompt or output content by default.
- Production database users are created from `deploy/postgres/least_privilege.sql`. The migrator
  owns schema changes; the runtime role only receives DML and sequence permissions.

CI runs Bandit, pip-audit, Gitleaks, and a Trivy scan of the production image. High or critical image
findings, detected secrets, dependency vulnerabilities, and source findings fail the security job.

## Operational checks

```bash
# Application quality gate
make check

# Local security checks
bandit -q -r src/company_lens -ll -ii
pip-audit

# Verify metrics
curl --fail http://localhost:8000/metrics

# Apply migrations, including persisted correlation IDs
alembic upgrade head
```

The `/metrics` endpoint must be private at the ingress or service-mesh layer in production. Langfuse
and database credentials must never be placed in source-controlled `.env` files.
