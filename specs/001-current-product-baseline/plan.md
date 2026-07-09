# Implementation Plan: Current Product Baseline

**Branch**: `main` | **Date**: 2026-07-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-current-product-baseline/spec.md`

## Summary

Capture the existing CompanyLens product surface as a Spec Kit baseline backlog. The artifact documents current user-visible capabilities, acceptance criteria, and follow-up validation tasks across research routing, SEC/FRED/PDF ingestion, retrieval, deterministic analytics, evidence validation, persistent sessions, API/SSE contracts, and the web research UI.

## Technical Context

**Language/Version**: Python 3.12 backend; TypeScript/React web frontend.

**Primary Dependencies**: FastAPI, SQLAlchemy, Alembic, LangGraph, OpenAI SDK, Langfuse, psycopg, Pydantic, httpx, pdfplumber, tiktoken, React, Vite, Playwright.

**Storage**: PostgreSQL for dev truth, research sessions, runs, events, checkpoints, source caches, financial facts, macro observations, and document/index metadata.

**Testing**: pytest for backend; pnpm lint/typecheck/test/build and Playwright for web/e2e.

**Target Platform**: Local Docker dev stack and server/web deployment surfaces.

**Project Type**: Python API/agent service with React web application.

**Performance Goals**: Bounded agent execution, adaptive context budgets, replayable SSE streams, and deterministic calculations over validated source data.

**Constraints**: Public traces must not expose raw prompts, provider bodies, hidden reasoning, credentials, raw retrieved passages, SQL errors, stack traces, or citation-invalid drafts. Dev data checks must use `.env` and the Docker dev stack.

**Scale/Scope**: Current baseline covers existing product behavior only. New product features should get their own Spec Kit specs.

## Constitution Check

- Evidence-first answers: PASS. The baseline requires answer claims to be backed by evidence envelopes or abstention.
- Deterministic data paths: PASS. Financial and macro questions route to structured facts and deterministic calculations.
- Source lineage and citation safety: PASS. The baseline includes provenance, lineage, and citation validation requirements.
- Durable research sessions: PASS. The baseline documents PostgreSQL-backed sessions, runs, events, checkpoints, leases, cancellation, and resume behavior.
- Observable, tested delivery: PASS. The baseline includes privacy-safe public trace events and focused test coverage areas.

## Project Structure

### Documentation (this feature)

```text
specs/001-current-product-baseline/
├── spec.md
├── plan.md
├── tasks.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
src/company_lens/
├── agent/
├── analytics/
├── api/
├── db/
├── evidence/
├── financials/
├── ingestion/
├── macro/
├── observability/
├── processing/
├── research/
└── retrieval/

web/src/
├── api/
├── components/
└── research/

tests/
└── agent_workflow/
```

**Structure Decision**: This baseline references the existing backend, web, docs, migrations, and tests. No new source structure is introduced.

## Complexity Tracking

No constitution violations are required for this baseline backlog.
