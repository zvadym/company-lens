<div align="center">

# 🔎 CompanyLens

### Agentic public-company intelligence powered by RAG, structured data, and tool calling

[![Project Status](https://img.shields.io/badge/status-early%20development-orange)](https://github.com/zvadym/company-lens)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-RAG-1C3C3C)](https://python.langchain.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent%20Orchestration-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![React](https://img.shields.io/badge/React-Interactive%20UI-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-Containers-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

**CompanyLens** is a production-oriented AI research assistant for analysing public companies across regulatory filings, investor documents, financial facts, and macroeconomic data.

It combines **retrieval-augmented generation**, **agentic orchestration**, **structured SQL queries**, **external APIs**, **calculations**, **chart generation**, and **source-level citations** in one observable workflow.

</div>

> [!IMPORTANT]
> CompanyLens is currently in **early development**. This README describes the intended MVP architecture, scope, and engineering standards. Features marked as planned are not yet implemented.

---

## 📌 Table of contents

- [Problem](#-problem)
- [What CompanyLens does](#-what-companylens-does)
- [Example questions](#-example-questions)
- [Core capabilities](#-core-capabilities)
- [System architecture](#-system-architecture)
- [Agent workflow](#-agent-workflow)
- [Data sources](#-data-sources)
- [RAG and indexing strategy](#-rag-and-indexing-strategy)
- [Structured analytics](#-structured-analytics)
- [Citations and evidence](#-citations-and-evidence)
- [Execution trace](#-execution-trace)
- [Technology stack](#-technology-stack)
- [Planned repository structure](#-planned-repository-structure)
- [API design](#-api-design)
- [Evaluation strategy](#-evaluation-strategy)
- [Observability and reliability](#-observability-and-reliability)
- [Security](#-security)
- [Development roadmap](#-development-roadmap)
- [Local development](#-local-development)
- [Design principles](#-design-principles)
- [License](#-license)

---

## 🎯 Problem

Public-company research usually requires switching between several incompatible sources:

- SEC filings in HTML or text form;
- annual reports and investor presentations in PDF;
- structured financial facts exposed through APIs;
- macroeconomic time series;
- manually created spreadsheets and charts;
- narrative explanations that must remain traceable to their sources.

A normal document chatbot is not enough for this domain. Some questions require semantic retrieval, some require SQL or API calls, some require calculations, and complex questions require all of them together.

CompanyLens is designed to choose the correct workflow for each question instead of forcing every request through vector search.

---

## 🧭 What CompanyLens does

CompanyLens accepts a natural-language research question and plans a multi-step workflow using the available evidence sources and tools.

Depending on the question, it can:

1. identify companies, metrics, reporting periods, and comparison criteria;
2. retrieve relevant passages from filings and investor documents;
3. query structured financial facts from PostgreSQL or external APIs;
4. fetch macroeconomic time series;
5. calculate growth rates, margins, trends, and comparisons;
6. generate a chart specification and render it in the UI;
7. compose a grounded answer with source citations;
8. expose the execution trace, tool calls, timing, and validation results.

The project is intended to demonstrate production engineering around LLM systems rather than only prompt engineering.

---

## 💬 Example questions

### Document retrieval

> What competitive risks did Cloudflare identify in its latest annual report?

### Structured analytics

> Show Datadog's year-over-year revenue growth for the last eight reported quarters.

### Hybrid RAG + analytics

> Compare the revenue growth of Cloudflare, Datadog, and MongoDB over the last eight quarters. Identify the two most frequently reported business risks for each company and plot growth against the federal funds rate.

### Cross-document comparison

> How did management's discussion of AI-related demand change between the last two annual reports?

### Tool-based research

> Retrieve the latest available federal funds rate and explain whether higher rates overlap with slower SaaS revenue growth.

### Evidence verification

> Which sources support the claim that customer optimisation affected cloud-software growth?

---

## ✨ Core capabilities

| Capability | Description | Planned implementation |
|---|---|---|
| 🔍 Semantic retrieval | Search narrative sections from filings and PDFs | LangChain + pgvector |
| 🧭 Agentic routing | Select RAG, SQL, API, calculation, or hybrid workflows | LangGraph |
| 🧾 Structured extraction | Convert model output into validated typed objects | Pydantic |
| 🧮 Financial calculations | Compute growth, margins, deltas, and comparisons | Python analytics layer |
| 📊 Chart generation | Return structured chart specifications to the frontend | Vega-Lite or Recharts |
| 🔗 Citations | Link claims to exact documents, sections, pages, or API series | Evidence registry |
| ⚡ Streaming | Stream status events, tool execution, and answer tokens | FastAPI + SSE |
| 🧠 Conversation context | Preserve user intent without polluting retrieval | LangGraph state/checkpoints |
| ✅ Validation | Reject unsupported claims and malformed tool output | Deterministic validators |
| 📈 Observability | Trace nodes, prompts, retrieval, latency, and failures | OpenTelemetry + Langfuse |
| 🧪 Evaluation | Measure retrieval quality, citation accuracy, and answer quality | Automated eval suite |
| 🐳 Reproducible runtime | Run services locally and in CI using containers | Docker Compose |

---

## 🏗 System architecture

```mermaid
flowchart LR
    U[User] --> UI[React application]
    UI -->|HTTP + SSE| API[FastAPI gateway]
    API --> G[LangGraph research agent]

    G --> R[Retrieval service]
    G --> S[Structured analytics service]
    G --> T[External tool adapters]
    G --> C[Calculation and chart service]
    G --> V[Evidence validator]

    R --> PG[(PostgreSQL + pgvector)]
    R --> OBJ[(Document storage)]

    S --> PG

    T --> SEC[SEC EDGAR / XBRL APIs]
    T --> FRED[FRED API]

    C --> PG

    G --> O[Tracing and evaluation]
    API --> O

    V --> G
    G --> API
    API --> UI
```

### Main boundaries

- **API layer** handles authentication, validation, streaming, rate limits, and request lifecycle.
- **Agent layer** plans and coordinates work but does not contain provider-specific network code.
- **Retrieval layer** owns document search, metadata filtering, reranking, and source hydration.
- **Analytics layer** owns deterministic queries and calculations.
- **Tool adapters** isolate external APIs behind typed interfaces.
- **Evidence layer** maps generated claims to retrieved or calculated evidence.
- **Frontend** renders answers, sources, charts, execution steps, and recoverable errors.

---

## 🕸 Agent workflow

The workflow is modelled as an explicit state machine rather than an open-ended autonomous loop.

```mermaid
flowchart TD
    A[Receive question] --> B[Parse intent and entities]
    B --> C[Resolve companies, tickers, and periods]
    C --> D[Create execution plan]

    D --> E{Required evidence}

    E -->|Narrative evidence| F[Retrieve documents]
    E -->|Financial metrics| G[Query structured facts]
    E -->|Macroeconomic data| H[Call external API]
    E -->|Derived values| I[Run calculations]

    F --> J[Merge evidence]
    G --> J
    H --> J
    I --> J

    J --> K{Chart required?}
    K -->|Yes| L[Generate chart specification]
    K -->|No| M[Compose grounded answer]
    L --> M

    M --> N[Validate claims and citations]
    N -->|Valid| O[Stream final result]
    N -->|Missing evidence| P[Repair or abstain]
    P --> O
```

### Planned LangGraph nodes

```text
parse_question
resolve_entities
plan_request
retrieve_documents
query_financial_facts
query_macro_series
calculate_metrics
generate_chart_spec
merge_evidence
generate_answer
validate_citations
finalize_response
```

### Planned agent state

```python
class AgentState(TypedDict):
    messages: list
    question: str
    intent: str
    companies: list[str]
    metrics: list[str]
    date_range: dict | None
    plan: list[dict]
    retrieved_documents: list[dict]
    tool_results: list[dict]
    calculations: list[dict]
    chart_spec: dict | None
    citations: list[dict]
    validation_errors: list[str]
    final_answer: str | None
```

---

## 🗂 Data sources

The MVP will use a deliberately small, high-quality corpus covering a limited set of public software companies.

### 1. SEC filings — HTML and text

Planned document types:

- 10-K annual reports;
- 10-Q quarterly reports;
- selected 8-K filings;
- filing exhibits where relevant.

High-value sections include:

- Business;
- Risk Factors;
- Management's Discussion and Analysis;
- Liquidity and Capital Resources;
- Competition;
- Market Risk;
- Strategy and Outlook.

### 2. Investor-relations documents — PDF

Planned document types:

- annual reports;
- investor presentations;
- shareholder letters;
- earnings presentations;
- selected sustainability reports.

PDF ingestion will preserve page numbers and document structure so the UI can open the exact supporting page.

### 3. SEC Company Facts — JSON

Structured financial facts may include:

- revenue;
- net income;
- operating income;
- assets;
- cash and equivalents;
- R&D expense;
- operating cash flow.

These values will be normalised into relational tables rather than embedded as text.

### 4. FRED — time-series API

Initial macroeconomic series may include:

- federal funds rate;
- CPI inflation;
- unemployment rate;
- Treasury yields;
- GDP growth.

### Initial company universe

The first corpus is expected to cover approximately five public software companies, for example:

- Cloudflare;
- Datadog;
- MongoDB;
- Snowflake;
- Elastic.

The exact list may change based on filing consistency and data quality.

---

## 🧠 RAG and indexing strategy

CompanyLens separates narrative evidence from structured numerical data.

### Content stored in pgvector

- narrative filing sections;
- risk disclosures;
- management commentary;
- strategy descriptions;
- investor-presentation text;
- shareholder letters;
- official company announcements.

### Content stored relationally

- company identifiers and tickers;
- filing metadata;
- reporting periods;
- financial facts;
- macroeconomic observations;
- calculated metrics;
- ingestion state;
- document versions;
- evaluation datasets.

### Planned chunk metadata

```python
class DocumentChunk:
    id: UUID
    company_id: UUID
    source_type: str
    document_type: str
    filing_date: date
    fiscal_period: str | None
    section: str
    page_number: int | None
    text: str
    source_url: str
    accession_number: str | None
    content_hash: str
    embedding: list[float]
```

### Retrieval pipeline

```mermaid
flowchart LR
    Q[Question] --> QE[Query understanding]
    QE --> MF[Metadata filters]
    MF --> VS[Vector search]
    MF --> KS[Keyword search]
    VS --> RR[Reranker]
    KS --> RR
    RR --> DD[Deduplication and diversity]
    DD --> SH[Source hydration]
    SH --> EV[Evidence package]
```

The planned retrieval strategy includes:

1. entity-aware metadata filtering;
2. hybrid dense and lexical retrieval;
3. reranking;
4. section and document diversity controls;
5. near-duplicate removal;
6. evidence compression only after source preservation;
7. retrieval diagnostics stored with every answer.

Embeddings answer **where a topic is discussed**. SQL and APIs answer **how much, when, and how values changed**.

---

## 📊 Structured analytics

Financial analysis must be deterministic and reproducible.

The LLM may select a metric or request a calculation, but it must not invent values or perform opaque arithmetic inside prose.

Planned calculation tools include:

- quarter-over-quarter growth;
- year-over-year growth;
- compound annual growth rate;
- gross and operating margins;
- absolute and percentage deltas;
- rolling averages;
- normalised index comparisons;
- simple correlation with explicit caveats.

Each calculated value will retain lineage:

```text
result
├── formula
├── input observations
├── source identifiers
├── reporting periods
├── units
└── calculation timestamp
```

Charts will be generated from validated structured datasets, not extracted from natural-language model output.

---

## 🔗 Citations and evidence

A citation is treated as a first-class domain object.

Planned citation types:

- SEC filing section;
- PDF page;
- investor-relations document;
- structured financial fact;
- FRED series observation;
- derived calculation.

Every externally verifiable claim should map to at least one evidence item. The validator will check that:

- the cited source exists;
- the cited passage or value was actually available to the model;
- company and reporting-period metadata match the claim;
- calculated values reference their inputs;
- unsupported claims are removed, repaired, or explicitly marked as unavailable.

---

## 👣 Execution trace

The UI will display structured execution events, not hidden model reasoning.

Example:

```text
✓ Detected intent: comparative financial analysis
✓ Resolved entities: Cloudflare [NET], Datadog [DDOG]
✓ Selected sources: SEC Company Facts, 10-K Risk Factors, FRED
✓ Retrieved 14 document chunks
✓ Loaded 16 quarterly revenue observations
✓ Calculated year-over-year growth
✓ Generated line-chart specification
✓ Verified 7 citations
```

Each trace event may include:

- LangGraph node name;
- status and duration;
- tool name and typed parameters;
- cache hit or miss;
- number of retrieved documents;
- retrieval scores;
- API response status;
- validation result;
- recoverable error details.

Sensitive prompts, credentials, and hidden chain-of-thought content will never be exposed.

---

## 🧰 Technology stack

### Backend

| Technology | Responsibility |
|---|---|
| Python 3.12+ | Core runtime |
| FastAPI | HTTP API, validation, streaming |
| Pydantic | Typed contracts and structured outputs |
| LangChain | Document abstractions, retrieval components, model adapters |
| LangGraph | Stateful orchestration, branching, retries, checkpoints |
| SQLAlchemy | Database access and migrations integration |
| Alembic | Schema migrations |
| PostgreSQL | Relational data and application state |
| pgvector | Embedding storage and similarity search |
| httpx | Async external API clients |
| Pandas or Polars | Deterministic data transformations |

### Frontend

| Technology | Responsibility |
|---|---|
| React | Application UI |
| TypeScript | Typed frontend contracts |
| TanStack Query | Server-state management |
| SSE client | Streaming agent events |
| Recharts or Vega-Lite | Interactive charts |
| Markdown renderer | Answers with citations |

### Infrastructure and quality

| Technology | Responsibility |
|---|---|
| Docker Compose | Local service orchestration |
| pytest | Unit and integration testing |
| Ruff | Linting and formatting |
| mypy or Pyright | Static type checking |
| pre-commit | Local quality gates |
| GitHub Actions | CI pipeline |
| OpenTelemetry | Distributed traces and metrics |
| Langfuse | LLM traces, prompt versions, and evaluation |
| Redis | Optional caching and rate-limit state |

The model provider will remain configurable so the core application is not tightly coupled to one vendor.

---

## 🗃 Planned repository structure

```text
company-lens/
├── apps/
│   ├── api/                     # FastAPI application
│   └── web/                     # React application
├── src/company_lens/
│   ├── agents/                  # LangGraph definitions and state
│   ├── api/                     # Routes, dependencies, SSE contracts
│   ├── analytics/               # Deterministic calculations
│   ├── citations/               # Evidence and citation validation
│   ├── config/                  # Settings and environment handling
│   ├── db/                      # Models, repositories, migrations
│   ├── ingestion/               # SEC/PDF ingestion pipelines
│   ├── llm/                     # Provider-neutral model interfaces
│   ├── retrieval/               # Search, filters, reranking
│   ├── tools/                   # SEC, FRED, and internal tools
│   └── observability/           # Traces, metrics, logging
├── evals/
│   ├── datasets/                # Curated evaluation questions
│   ├── retrieval/               # Retrieval metrics
│   ├── answers/                 # Groundedness and citation checks
│   └── regression/              # Versioned regression suites
├── tests/
│   ├── unit/
│   ├── integration/
│   └── end_to_end/
├── scripts/                     # Development and ingestion commands
├── infra/                       # Container and deployment assets
├── docs/                        # Architecture decisions and diagrams
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## 🔌 API design

Planned public endpoints:

```http
POST /api/v1/research
GET  /api/v1/research/{run_id}
GET  /api/v1/research/{run_id}/events
GET  /api/v1/research/{run_id}/sources
POST /api/v1/feedback
GET  /api/v1/companies
GET  /api/v1/health
```

### Example request

```json
{
  "question": "Compare Cloudflare and Datadog revenue growth over the last eight quarters and explain the main risks reported by each company.",
  "conversation_id": null,
  "options": {
    "include_chart": true,
    "show_execution_trace": true
  }
}
```

### Example streamed event

```text
event: agent.step
data: {
  "run_id": "run_123",
  "node": "query_financial_facts",
  "status": "completed",
  "duration_ms": 184,
  "summary": "Loaded 16 quarterly revenue observations"
}
```

### Example result shape

```json
{
  "answer": "...",
  "citations": [],
  "chart": {
    "type": "line",
    "dataset": [],
    "x": "quarter",
    "y": "revenue_growth",
    "series": "company"
  },
  "execution_summary": [],
  "warnings": []
}
```

---

## 🧪 Evaluation strategy

CompanyLens will include evaluation from the beginning rather than treating it as a final polish step.

### Retrieval evaluation

- Recall@K;
- Precision@K;
- Mean Reciprocal Rank;
- metadata-filter accuracy;
- section diversity;
- duplicate rate;
- reranker lift.

### Answer evaluation

- factual correctness;
- evidence completeness;
- citation precision;
- citation recall;
- numerical accuracy;
- instruction following;
- appropriate abstention;
- chart-to-answer consistency.

### Agent evaluation

- correct route selection;
- unnecessary tool-call rate;
- tool argument validity;
- successful recovery from transient failures;
- latency and cost by workflow;
- deterministic regression tests for graph transitions.

### Evaluation dataset

The repository will contain a versioned set of questions covering:

- single-document retrieval;
- cross-document comparison;
- numerical analysis;
- hybrid document and API questions;
- ambiguous company names;
- missing data;
- conflicting evidence;
- adversarial or unsupported requests.

LLM-as-a-judge may be used as one signal, but deterministic checks and source-grounded assertions remain primary wherever possible.

---

## 📡 Observability and reliability

Production-oriented safeguards are part of the planned MVP.

### Observability

- structured JSON logs;
- correlation and run IDs;
- per-node latency;
- token and model cost tracking;
- retrieval diagnostics;
- external API timings;
- cache metrics;
- citation-validation results;
- user feedback linked to execution traces.

### Reliability

- explicit timeouts;
- bounded retries with exponential backoff;
- circuit breakers for external APIs;
- idempotent ingestion;
- document content hashes;
- database transactions;
- graceful degradation when one source is unavailable;
- resumable LangGraph checkpoints;
- typed error taxonomy;
- provider fallback where appropriate.

### Performance goals for the MVP

These are initial engineering targets, not current benchmark results:

- first streamed status event in under 500 ms locally;
- simple retrieval answer in under 5 seconds under normal API conditions;
- hybrid analysis in under 15 seconds under normal API conditions;
- no silent citation failures;
- reproducible calculations for identical inputs;
- ingestion safe to rerun without duplicate records.

---

## 🔐 Security

Planned security controls include:

- secrets loaded only from environment or a secret manager;
- no credentials stored in prompts, traces, or source metadata;
- outbound requests restricted to approved tool adapters;
- input-size limits;
- rate limiting;
- prompt-injection-aware document handling;
- HTML sanitisation;
- source URL validation;
- least-privilege database roles;
- dependency and container scanning;
- audit events for privileged operations.

Retrieved documents are treated as untrusted data, not as system instructions.

---

## 🗺 Development roadmap

### Phase 1 — Foundation

- [ ] Bootstrap Python project and quality tooling
- [ ] Add PostgreSQL and pgvector through Docker Compose
- [ ] Define database schema and migrations
- [ ] Add FastAPI health endpoint
- [ ] Add CI for linting, typing, and tests

### Phase 2 — Ingestion

- [ ] Implement company and filing metadata ingestion
- [ ] Download and parse selected SEC filings
- [ ] Add PDF ingestion with page metadata
- [ ] Implement deterministic section extraction
- [ ] Add idempotency and content hashing

### Phase 3 — Retrieval

- [ ] Generate embeddings
- [ ] Add pgvector search
- [ ] Add metadata filters
- [ ] Add lexical retrieval
- [ ] Add reranking and deduplication
- [ ] Create retrieval evaluation dataset

### Phase 4 — Structured data and tools

- [ ] Implement SEC Company Facts adapter
- [ ] Normalise financial observations
- [ ] Implement FRED adapter
- [ ] Add typed calculation tools
- [ ] Add caching and rate-limit handling

### Phase 5 — LangGraph agent

- [ ] Add intent and entity extraction
- [ ] Add explicit planning and route selection
- [ ] Run independent tools in parallel
- [ ] Add checkpoints and recoverable errors
- [ ] Add evidence merge and citation validation

### Phase 6 — User interface

- [ ] Build React chat interface
- [ ] Stream execution events over SSE
- [ ] Render source cards and document previews
- [ ] Render interactive charts
- [ ] Add feedback controls

### Phase 7 — Production readiness

- [ ] Add OpenTelemetry and Langfuse
- [ ] Add end-to-end and regression tests
- [ ] Add security checks
- [ ] Add performance benchmarks
- [ ] Add deployment configuration
- [ ] Publish architecture decision records

---

## 🚀 Local development

The executable development environment will be added during Phase 1.

The intended workflow is:

```bash
# Clone the repository
git clone https://github.com/zvadym/company-lens.git
cd company-lens

# Copy local configuration
cp .env.example .env

# Start PostgreSQL, pgvector, API, and supporting services
docker compose up --build

# Run backend checks
make check

# Run the evaluation suite
make eval
```

Planned environment variables:

```dotenv
DATABASE_URL=postgresql+psycopg://company_lens:company_lens@localhost:5432/company_lens
LLM_PROVIDER=openai
LLM_MODEL=
EMBEDDING_MODEL=
OPENAI_API_KEY=
FRED_API_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=
```

Do not commit real credentials. A complete `.env.example` will be added with the first runnable version.

---

## 🧱 Design principles

1. **Use the right data path.** Narrative questions use retrieval; numerical questions use structured data and deterministic calculations.
2. **Make orchestration explicit.** Agent behaviour is represented as inspectable LangGraph nodes and transitions.
3. **Treat evidence as data.** Citations, calculations, and source lineage are stored and validated.
4. **Keep model providers replaceable.** Business logic depends on internal interfaces, not directly on vendor SDKs.
5. **Prefer bounded autonomy.** Tools, retries, loops, and repair attempts have clear limits.
6. **Evaluate continuously.** Retrieval, answers, citations, routing, latency, and cost are regression-tested.
7. **Expose operational behaviour.** The user can see execution status and sources without exposing hidden reasoning.
8. **Fail visibly.** Missing data, conflicting evidence, and unavailable tools are represented explicitly.
9. **Build for reproducibility.** Calculations and ingestion are deterministic and traceable.
10. **Keep the MVP focused.** A small, curated company universe is preferable to a large, unreliable corpus.

---

## 🤝 Contributing

The contribution workflow will be documented after the project skeleton is in place. Planned standards include:

- focused pull requests;
- tests for behavioural changes;
- typed public interfaces;
- architecture decision records for major design changes;
- no provider-specific logic inside domain services;
- benchmark evidence for retrieval or performance changes.

---

## 📄 License

A license has not been selected yet. Until a license is added, the repository remains publicly viewable but does not grant general permission to copy, modify, or redistribute the code.

---

<div align="center">

Built as a production-oriented demonstration of **RAG**, **agentic workflows**, **tool calling**, **structured analytics**, and **observable AI systems**.

</div>
