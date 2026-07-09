# Implementation Plan: ML Reranker Service

**Branch**: `61/ml-reranker-service` | **Date**: 2026-07-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-ml-reranker-service/spec.md`

## Summary

Add optional second-stage ML reranking for document retrieval candidates while keeping the main CompanyLens backend image lightweight. The backend will keep `NoopReranker` as the default, add an HTTP reranker adapter behind configuration, and call a separate internal reranker service image for local ML scoring. Reranked results must preserve existing evidence lineage, citation metadata, dedupe, diversity, privacy-safe diagnostics, and graceful fallback behavior.

## Technical Context

**Language/Version**: Python 3.12 backend and reranker service.

**Primary Dependencies**: Existing backend dependencies: FastAPI, Pydantic, SQLAlchemy, httpx, OpenTelemetry, pytest. New reranker-service-only dependencies: FastAPI or equivalent ASGI server, sentence-transformers CrossEncoder, Torch runtime pulled only into the reranker image.

**Storage**: PostgreSQL remains the source of truth for documents, chunks, runs, events, sessions, and checkpoints. The reranker service uses no application database; it may use a container volume for model cache.

**Testing**: pytest for backend and service unit tests; Docker Compose smoke validation for the real reranker image; existing `make check` must continue to pass with reranking disabled.

**Target Platform**: Linux containers in local Docker dev stack and deployable server environments.

**Project Type**: Python API/agent service plus one internal ML scoring microservice.

**Performance Goals**: Score the current retrieval candidate pool in one batched request; keep default backend startup independent of model download; keep reranker timeout bounded so research runs can fall back instead of hanging.

**Constraints**: Reranking is disabled by default. Backend image must not depend on Torch, Transformers, or sentence-transformers. Reranker diagnostics must not expose raw chunk text, prompts, provider payloads, credentials, stack traces, or hidden reasoning. Dev-data validation must use `.env` and Docker dev stack.

**Scale/Scope**: Issue #61 only. Applies to document retrieval candidates before final top-k evidence selection. Does not include query rewriting, multi-query retrieval, structured financial fact reranking, or GPU deployment automation.

## Constitution Check

- Evidence-first answers: PASS. Reranking changes document evidence order only; answers still come from bounded evidence envelopes or abstention.
- Deterministic data paths: PASS. Structured financial facts, macro observations, calculations, and chart data remain outside this feature.
- Source lineage and citation safety: PASS. Reranked chunks must preserve existing source metadata, evidence IDs, filters, dedupe, diversity, and validation flow.
- Durable research sessions: PASS. Reranking happens inside the existing retrieval tool path and does not alter PostgreSQL checkpoint/session ownership.
- Observable, tested delivery: PASS. The plan requires typed contracts, privacy-safe diagnostics, fallback tests, and no raw chunk text in traces.

## Project Structure

### Documentation (this feature)

```text
specs/002-ml-reranker-service/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── backend-reranker-config.md
│   └── reranker-service.openapi.yaml
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
src/company_lens/
├── config.py
├── agent/
│   ├── application.py
│   └── tools.py
├── observability/
│   └── telemetry.py
└── retrieval/
    ├── adaptive.py
    ├── rerank.py
    ├── schemas.py
    └── service.py

tests/
├── test_config.py
├── test_retrieval.py
└── test_retrieval_postgres.py

reranker/
├── company_lens_reranker/
│   ├── app.py
│   ├── schemas.py
│   └── scoring.py
└── tests/

Dockerfile.reranker
docker-compose.dev.yml
README.md
web/README.md
```

**Structure Decision**: Keep backend integration inside existing retrieval boundaries. Add a top-level `reranker/` service package so ML dependencies are isolated from `src/company_lens` and the backend wheel. Docker Compose wires the optional service through a profile or explicit environment override.

## Phase 0: Research

Research decisions are documented in [research.md](./research.md). All technical context unknowns are resolved:

- reranker model/runtime choice;
- backend integration point;
- failure and fallback behavior;
- service boundary and Docker layout;
- diagnostics and privacy constraints;
- test strategy without CI model downloads.

## Phase 1: Design And Contracts

Generated design artifacts:

- [data-model.md](./data-model.md)
- [contracts/reranker-service.openapi.yaml](./contracts/reranker-service.openapi.yaml)
- [contracts/backend-reranker-config.md](./contracts/backend-reranker-config.md)
- [quickstart.md](./quickstart.md)

Agent context update script: skipped. This Spec Kit installation does not include an agent-context update script under `.specify/scripts/`.

## Post-Design Constitution Check

- Evidence-first answers: PASS. No answer generation shortcut is introduced.
- Deterministic data paths: PASS. Financial and macro paths remain deterministic and unrereanked.
- Source lineage and citation safety: PASS. Contracts require opaque candidate IDs and backend-owned lineage preservation.
- Durable research sessions: PASS. The feature does not change checkpoint, queue, session, or worker lease semantics.
- Observable, tested delivery: PASS. Contracts and quickstart require privacy-safe diagnostics, test doubles, and bounded fallback behavior.

## Complexity Tracking

No constitution violations are required.
