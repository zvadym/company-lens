# CompanyLens web application

The frontend is a Vite, React, and TypeScript application. It uses assistant-ui for the research
thread, TanStack Query for API state, native `EventSource` for resumable SSE, and Recharts for
validated chart specifications.

## Run locally

Run the full Docker developer stack from the repository root:

```bash
make migrate-dev-docker
make start-dev-docker
```

`make migrate-dev-docker` applies backend migrations and initializes the LangGraph checkpoint
tables required by research runs.

To populate the initial company universe and build the retrieval index, run:

```bash
make index-dev
```

Use `DEV_EMBEDDING_PROVIDER=local make index-dev` for a cheaper local smoke-test index.

Open <http://localhost:5173>. The API is available at <http://localhost:8000>.

The backend dev containers load the repository `.env` file if it exists. Docker-specific
environment values from `docker-compose.dev.yml` still override it.

If host port `5432` is busy, run the stack with another exposed Postgres port:

```bash
COMPANY_LENS_DEV_POSTGRES_PORT=5433 make start-dev-docker
```

To opt into the separate ML reranker service locally, start the dev stack with the
`reranker` Compose profile and point the backend at the internal service:

```bash
COMPOSE_PROFILES=reranker \
COMPANY_LENS_RERANKER_PROVIDER=http \
make start-dev-docker
```

The reranker image is built from `Dockerfile.reranker` and installs only the dependencies from
`reranker/pyproject.toml`, including `sentence-transformers` and its Torch runtime. The API and
worker images keep using `Dockerfile.dev` and do not install those ML dependencies. Model files are
cached in the `reranker-model-cache` Docker volume mounted at `/models`; the first startup may
download weights, while later restarts reuse the volume unless it is removed.

Useful local overrides:

```bash
COMPANY_LENS_RERANKER_SERVICE_MODEL_NAME=cross-encoder/ms-marco-MiniLM-L6-v2
COMPANY_LENS_RERANKER_SERVICE_BATCH_SIZE=16
COMPANY_LENS_RERANKER_SERVICE_MAX_LENGTH=512
COMPANY_LENS_RERANKER_TIMEOUT_SECONDS=2.0
```

For non-Docker development, start PostgreSQL, apply migrations, and run the API and worker from
the repository root:

```bash
docker compose up -d postgres
alembic upgrade head
make run-api
make run-worker
```

In another terminal, install and run the web application:

```bash
corepack enable
make web-install
make web-dev
```

Open <http://127.0.0.1:5173>. Vite proxies `/api` requests to `http://127.0.0.1:8000`.

## Quality checks

```bash
make web-check
make web-e2e
```

The end-to-end test mocks the API and SSE stream, so it does not require PostgreSQL, the worker,
or model credentials.

## API types

The checked-in `openapi.json` and `src/api/schema.d.ts` keep the HTTP contract reviewable. After a
backend schema change, regenerate the snapshot and TypeScript declarations:

```bash
PYTHONPATH=src python -c \
  'import json; from pathlib import Path; from company_lens.main import create_app; Path("web/openapi.json").write_text(json.dumps(create_app().openapi(), indent=2) + "\n")'
make web-api-types
```

Public SSE events are additionally validated at runtime with the discriminated Zod schemas in
`src/research/events.ts`. Unknown or malformed event versions are ignored rather than rendered.
