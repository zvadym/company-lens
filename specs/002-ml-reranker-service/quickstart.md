# Quickstart: ML Reranker Service

This guide validates the reranker feature after implementation. It is not an implementation task list.

## Prerequisites

From the repository root:

```bash
test -f .env
```

If `.env` is missing, create it before running development commands or database checks.

## Backend Checks With Reranking Disabled

Reranking is disabled by default. Existing checks should still pass:

```bash
make check
```

Expected outcome:

- Existing retrieval behavior remains available.
- Backend starts without ML dependencies.
- Tests do not download model weights.

## Unit Validation With Fake Reranker

Run focused tests for backend reranker integration:

```bash
pytest tests/test_retrieval.py tests/test_config.py -q
(cd reranker && pytest)
```

Expected outcome:

- Fake reranker scores can reorder candidates.
- Timeout, invalid response, service unavailable, partial scores, and strict failure mode are covered.
- Diagnostics include provider status, candidate count, scored count, model identity when available, fallback reason, score, and rank.

## Local Docker Smoke With Real Reranker

Start the dev stack with the reranker service enabled once implementation adds the compose profile or override:

```bash
make migrate-dev-docker
COMPOSE_PROFILES=reranker \
COMPANY_LENS_RERANKER_PROVIDER=http \
make start-dev-docker
```

Expected outcome:

- API and worker images do not install Torch or sentence-transformers.
- The reranker service image loads the configured model.
- Retrieval calls use non-noop reranker diagnostics when provider is `http`.
- Stopping the reranker service in graceful fallback mode does not prevent retrieval results.

## Manual Retrieval Comparison

Prepare indexed data using the Docker dev stack:

```bash
make index-dev
```

Run a retrieval benchmark or focused retrieval command once implementation exposes the reranker comparison path.

```bash
company-lens benchmark-retrieval \
  --dataset evals/retrieval/golden/synthetic.yaml \
  --compare-reranking \
  --output-json /tmp/company-lens-reranking-report.json
```

Expected outcome:

- Baseline and reranked runs are distinguishable in diagnostics.
- Reranked output includes model identity and per-result reranker ranks.
- Source lineage and citation metadata remain unchanged.

## Privacy Verification

Inspect public trace events and retrieval diagnostics.

Expected outcome:

- Diagnostics include status, counts, model identity, latency, fallback reason, and result ranks/scores.
- Diagnostics do not expose raw chunk text, raw reranker request/response payloads, credentials, stack traces, or hidden reasoning.
