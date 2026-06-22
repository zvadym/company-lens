# CompanyLens web application

The frontend is a Vite, React, and TypeScript application. It uses assistant-ui for the research
thread, TanStack Query for API state, native `EventSource` for resumable SSE, and Recharts for
validated chart specifications.

## Run locally

Start PostgreSQL, apply migrations, and run the API and worker from the repository root:

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
