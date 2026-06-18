<div align="center">

# 🔎 CompanyLens

### Agentic public-company intelligence powered by adaptive RAG, structured data, and tool calling

[![Project Status](https://img.shields.io/badge/status-early%20development-orange)](https://github.com/zvadym/company-lens/issues)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-RAG-1C3C3C)](https://python.langchain.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent%20Orchestration-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![React](https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Evaluation](https://img.shields.io/badge/Evaluation-Golden%20Sets%20%7C%20LLM--as--a--Judge-7B61FF)](https://github.com/zvadym/company-lens/issues/1)
[![Docker](https://img.shields.io/badge/Docker-Containers-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

**CompanyLens** is a production-oriented AI research assistant for analysing public companies across regulatory filings, investor documents, structured financial facts, and macroeconomic data.

It is designed as both a usable MVP and a hands-on laboratory for **RAG**, **agentic systems**, **tool calling**, **context engineering**, **evaluation**, and **LLM observability**.

</div>

> [!IMPORTANT]
> CompanyLens is currently in **early development**. The backend foundation is runnable; later RAG, agent, ingestion, evaluation, and UI capabilities are tracked in [GitHub Issues](https://github.com/zvadym/company-lens/issues).

---

## 📌 Contents

- [Why CompanyLens](#-why-companylens)
- [Example research question](#-example-research-question)
- [System architecture](#-system-architecture)
- [Data sources](#-data-sources)
- [Hierarchical data model](#-hierarchical-data-model)
- [Adaptive retrieval](#-adaptive-retrieval)
- [Agent workflow](#-agent-workflow)
- [Evidence and citations](#-evidence-and-citations)
- [Evaluation Lab](#-evaluation-lab)
- [Technology stack](#-technology-stack)
- [Planned repository structure](#-planned-repository-structure)
- [API and interface](#-api-and-interface)
- [Implementation roadmap](#-implementation-roadmap)
- [Quality targets](#-quality-targets)
- [Local development](#-local-development)
- [Design principles](#-design-principles)

---

## 🎯 Why CompanyLens

Public-company research usually requires moving between several incompatible sources:

- SEC filings in HTML or text form;
- annual reports and investor presentations in PDF;
- structured XBRL financial facts;
- macroeconomic time series;
- manually created calculations and charts;
- narrative explanations that must remain traceable to evidence.

A conventional document chatbot is not enough.

Different questions require different execution paths:

| Question type | Correct data path |
|---|---|
| What risks did management report? | RAG over filing sections |
| What was revenue growth? | Structured facts + deterministic calculation |
| How did risks change over three years? | Multi-document hierarchical retrieval |
| Compare growth with interest rates | SEC facts + FRED API + calculation + chart |
| What does ticker `NET` refer to? | Exact entity lookup, not vector search |

CompanyLens routes each request to the appropriate combination of retrieval, SQL, APIs, calculations, and generation.

---

## 💬 Example research question

> Compare Cloudflare, Datadog, and MongoDB revenue growth over the last eight quarters. Identify the two most frequently reported business risks for each company, explain whether management's outlook changed, and plot revenue growth against the federal funds rate.

A successful run should:

1. resolve company names, tickers, reporting periods, and metrics;
2. query structured SEC financial facts;
3. retrieve relevant 10-K and 10-Q sections;
4. fetch the federal funds rate from FRED;
5. calculate year-over-year growth;
6. generate a validated chart specification;
7. produce a grounded answer with claim-level citations;
8. expose a safe execution trace, latency, and quality checks.

---

## 🏗 System architecture

```mermaid
flowchart LR
    U[User] --> UI[React application]
    UI -->|HTTP + SSE| API[FastAPI API]
    API --> G[LangGraph research agent]

    G --> ER[Entity resolver]
    G --> P[Planner]
    G --> R[Adaptive retrieval]
    G --> S[Structured analytics]
    G --> T[External tools]
    G --> E[Evidence validator]

    R --> PG[(PostgreSQL + pgvector)]
    R --> DS[(Document storage)]
    S --> PG
    T --> SEC[SEC EDGAR / XBRL]
    T --> FRED[FRED API]

    G --> O[Observability and evaluation]
    API --> O

    E --> G
    G --> API
```

### Main boundaries

- **API layer** — request validation, streaming, rate limits, cancellation, and public errors.
- **Agent layer** — explicit state transitions, planning, parallel branches, retries, and checkpoints.
- **Retrieval layer** — exact filters, dense and lexical retrieval, reranking, hierarchy expansion, and context budgets.
- **Analytics layer** — deterministic queries, calculations, units, and data lineage.
- **Tool adapters** — SEC, FRED, model providers, and optional external systems behind typed interfaces.
- **Evidence layer** — claim-to-source mapping, citation validation, and abstention.
- **Evaluation layer** — golden datasets, deterministic metrics, LLM judges, regression gates, and online feedback.

---

## 🗂 Data sources

### SEC filings — HTML and text

Initial document types:

- 10-K annual reports;
- 10-Q quarterly reports;
- selected 8-K filings;
- relevant filing exhibits.

High-value sections include:

- Business;
- Risk Factors;
- Management's Discussion and Analysis;
- Liquidity and Capital Resources;
- Competition;
- Market Risk;
- Strategy and Outlook.

### Investor-relations documents — PDF

- annual reports;
- investor presentations;
- shareholder letters;
- earnings presentations;
- selected sustainability reports.

PDF ingestion must preserve page-level provenance so citations can open the exact supporting page.

### SEC Company Facts — JSON/XBRL

Structured metrics are normalised into relational tables rather than embedded as prose:

- revenue;
- net income;
- operating income;
- assets;
- cash and equivalents;
- R&D expense;
- operating cash flow.

The implemented Company Facts pipeline uses a [versioned canonical mapping](docs/financial-metrics.md),
retains duplicate/restatement provenance, and exposes typed ingestion and query commands:

```bash
company-lens ingest-company-facts --ticker NET
company-lens query-financial-facts --ticker NET --metric revenue --fiscal-year 2025
```

### FRED — time-series API

Initial series may include:

- federal funds rate;
- CPI inflation;
- unemployment rate;
- Treasury yields;
- GDP growth.

### Initial company universe

The first corpus is expected to cover approximately five public software companies:

- Cloudflare;
- Datadog;
- MongoDB;
- Snowflake;
- Elastic.

Availability is checked by the standalone diagnostics task in [#2](https://github.com/zvadym/company-lens/issues/2).

---

## 🧱 Hierarchical data model

CompanyLens will preserve document hierarchy instead of storing unrelated flat chunks.

```text
Company
└── Filing or investor document
    ├── Document metadata
    ├── Document summary
    ├── Section
    │   ├── Section summary
    │   └── Detailed chunks
    └── Raw pages or source artifacts
```

This supports several retrieval patterns:

- search summaries and expand to detailed source chunks;
- search small chunks and return larger parent sections;
- compare equivalent sections across reporting periods;
- preserve exact page and filing citations;
- reprocess summaries, chunks, or embeddings independently.

### Planned source lineage

```text
claim
└── evidence item
    ├── company and identifiers
    ├── document and filing metadata
    ├── section and page
    ├── retrieved passage or structured observation
    ├── parser, prompt, embedding, and index versions
    └── source URL
```

The data-model work is tracked in [#4](https://github.com/zvadym/company-lens/issues/4).

---

## 🧠 Adaptive retrieval

CompanyLens does not send the same amount of context for every question.

### Retrieval strategies

```text
none
summary_only
section_level
detailed
structured_only
hybrid
```

Examples:

```text
“What does Cloudflare do?”
    → company/document summaries

“What risks did Cloudflare identify?”
    → section summaries + supporting chunks

“How did those risks change over three years?”
    → multiple filings + hierarchy expansion + period diversity

“Show revenue for eight quarters.”
    → structured facts only
```

### Retrieval pipeline

```mermaid
flowchart LR
    Q[Question] --> ER[Exact entity resolution]
    ER --> RP[Retrieval plan and token budget]
    RP --> MF[Metadata constraints]

    MF --> VS[Vector search]
    MF --> KS[Lexical search]
    VS --> RR[Reranker]
    KS --> RR

    RR --> HD[Hierarchy expansion]
    HD --> DD[Deduplication and diversity]
    DD --> CA[Context assembler]
    CA --> QE[Context-quality evaluation]

    QE -->|Sufficient| EV[Evidence package]
    QE -->|Insufficient| ES[Bounded escalation]
    ES --> RP
```

### Exact lookup before embeddings

The following values must be resolved deterministically where possible:

- company names and aliases;
- tickers and CIKs;
- filing types and accession numbers;
- fiscal periods and dates;
- known financial metrics.

Vector search is then executed inside the correctly filtered corpus.

### Baseline retrieval commands

The first retrieval layer ranks `DocumentChunk` records, then attaches parent section,
document, company, and source metadata. It supports independent dense, lexical, and
hybrid modes.

```bash
# Build local deterministic feature-hashing embeddings for chunks
company-lens index-embeddings \
  --index-name default \
  --index-version local-feature-hashing.v1 \
  --batch-size 100

# Run hybrid retrieval with exact metadata filters applied before ranking
company-lens retrieve \
  --mode hybrid \
  --query "competition risk from security vendors" \
  --filing-form 10-K \
  --section-code risk_factors \
  --top-k 10

# Compare dense, lexical, and hybrid variants on the synthetic labelled set
company-lens benchmark-retrieval \
  --dataset evals/retrieval/golden/synthetic.yaml \
  --output-json retrieval-report.json

# Resolve entities, select a strategy, and return budgeted evidence with a trace
company-lens adaptive-retrieve \
  --query "Compare Cloudflare and Fastly risks in 2025" \
  --max-attempts 3
```

Every result includes source and parent IDs, document/section metadata, page and character
location when available, lexical/vector/reranker/hybrid scores, embedding index version,
the selected retrieval strategy, and deterministic diagnostics.

### Bounded escalation

When context is insufficient, the system may:

- rewrite the query;
- switch to lexical or exact search;
- expand a summary to its parent section;
- increase top-k within a fixed limit;
- add a structured-data tool;
- abstain after the maximum number of attempts.

Every retry must change the strategy. Repeating the same failed retrieval is not a recovery mechanism.

`adaptive-retrieve` returns evidence and citations rather than a generated prose answer.
Answer synthesis is handled by the later agent workflow.

Adaptive retrieval is tracked in [#8](https://github.com/zvadym/company-lens/issues/8) and [#9](https://github.com/zvadym/company-lens/issues/9).

---

## 🕸 Agent workflow

The agent is an explicit bounded state machine rather than an unrestricted autonomous loop.

```mermaid
flowchart TD
    A[Receive question] --> B[Parse intent and entities]
    B --> C[Resolve identifiers and periods]
    C --> D[Create execution plan]

    D --> E{Required evidence}
    E -->|Narrative| F[Adaptive retrieval]
    E -->|Financial| G[Query SEC facts]
    E -->|Macroeconomic| H[Query FRED]
    E -->|Derived metrics| I[Run calculations]

    F --> J[Evaluate context]
    J -->|Insufficient| K[Escalate retrieval]
    K --> F
    J -->|Sufficient| L[Merge evidence]
    G --> L
    H --> L
    I --> L

    L --> M{Chart required?}
    M -->|Yes| N[Generate chart specification]
    M -->|No| O[Generate grounded answer]
    N --> O

    O --> P[Extract claims and validate citations]
    P -->|Valid| Q[Stream result]
    P -->|Repairable| R[Repair answer]
    P -->|Unsupported| S[Abstain or return partial result]
    R --> P
```

### Planned LangGraph nodes

```text
parse_question
resolve_entities
plan_request
retrieve_documents
evaluate_context
query_financial_facts
query_macro_series
calculate_metrics
generate_chart_spec
merge_evidence
generate_answer
validate_citations
repair_or_abstain
finalize_response
```

### Planned agent state

```python
class AgentState(TypedDict):
    messages: list
    question: str
    intent: str
    resolved_entities: dict
    retrieval_plan: dict | None
    execution_plan: list[dict]
    retrieved_documents: list[dict]
    tool_results: list[dict]
    calculations: list[dict]
    evidence: list[dict]
    chart_spec: dict | None
    claims: list[dict]
    citations: list[dict]
    validation_errors: list[str]
    retry_count: int
    final_answer: str | None
```

Agent orchestration is tracked in [#12](https://github.com/zvadym/company-lens/issues/12).

---

## 🔗 Evidence and citations

A citation is a first-class domain object, not a URL appended after generation.

Planned evidence types:

- SEC filing passage;
- PDF page or text block;
- structured financial fact;
- FRED observation;
- deterministic calculation;
- derived chart dataset.

Validation checks include:

- the evidence existed in the assembled model context;
- company, period, document, page, metric, and unit match the claim;
- calculated values retain input observations and formula;
- unsupported factual claims are repaired, removed, or marked unavailable;
- correlation is not presented as proven causation.

The evidence registry and claim-level validation are tracked in [#13](https://github.com/zvadym/company-lens/issues/13).

---

## 🧪 Evaluation Lab

Evaluation is a separate subsystem, not a final testing step.

The umbrella design is tracked in [#1](https://github.com/zvadym/company-lens/issues/1).

```mermaid
flowchart TD
    G[Canonical golden dataset]

    G --> C[Custom deterministic evaluators]
    G --> R[Ragas]
    G --> D[DeepEval]
    G --> LS[LangSmith]
    G --> LF[Langfuse]
    G --> PH[Phoenix / OpenInference]

    H[Human annotations] --> JC[Judge calibration]
    C --> REP[Cross-framework report]
    R --> REP
    D --> REP
    LS --> REP
    LF --> REP
    PH --> REP
    REP --> JC

    PROD[Production traces and feedback] --> REVIEW[Human review]
    REVIEW --> G
```

### 1. Manual golden set

One framework-neutral dataset will define:

- question and category;
- reference answer or required claims;
- expected entities and date range;
- expected route and graph nodes;
- expected tools and arguments;
- expected documents, sections, and pages;
- expected calculations and chart properties;
- abstention expectations;
- rubric and human labels.

Planned initial size: **40-60 manually reviewed cases**.

Tracked in [#18](https://github.com/zvadym/company-lens/issues/18).

### 2. Deterministic evaluation

Where exact assertions are possible, normal code remains the source of truth:

- ingestion integrity;
- Recall@K, Precision@K, MRR, and nDCG@K;
- entity and route accuracy;
- tool names and arguments;
- LangGraph trajectories and retry bounds;
- financial calculations;
- chart datasets;
- citation metadata and lineage;
- latency, token, tool-call, and cost budgets.

Tracked in [#19](https://github.com/zvadym/company-lens/issues/19).

### 3. LLM-as-a-Judge

The project will demonstrate several judge patterns:

- pointwise rubric scoring;
- reference-based evaluation;
- reference-free groundedness evaluation;
- pairwise comparison;
- claim-level evidence verification;
- trajectory and tool-efficiency judging.

Judge prompts, models, schemas, and rubric versions will be stored with experiment results.

LLM judges will be calibrated against human labels using agreement, confusion matrices, Cohen's kappa, rank correlation, repeated runs, and position-bias tests.

Tracked in [#20](https://github.com/zvadym/company-lens/issues/20).

### 4. Framework comparison

The same canonical cases will be exposed through adapters for:

| Tool | Learning focus |
|---|---|
| pytest + custom metrics | Exact domain assertions and CI gates |
| Ragas | RAG, tool, agent, and synthetic test metrics |
| DeepEval | GEval, component tests, agent tests, and CI workflows |
| LangSmith | LangGraph traces, datasets, experiments, pairwise and human evaluation |
| Langfuse | Open observability, prompts, datasets, online scoring, cost and latency |
| Phoenix / OpenInference | OpenTelemetry-based LLM tracing and evaluator instrumentation |

The project intentionally includes overlapping tools for learning and comparison. A normal production deployment would usually select a smaller subset.

Tracked in [#21](https://github.com/zvadym/company-lens/issues/21).

### 5. Offline and online evaluation

```text
Pull request
    → fast deterministic regression subset

Main / nightly
    → complete golden set + model judges + comparison report

Production demo
    → deterministic checks on every run
    → sampled LLM judges
    → explicit user feedback
    → reviewed failures promoted into regression cases
```

Tracked in [#22](https://github.com/zvadym/company-lens/issues/22).

---

## 🧰 Technology stack

### Backend and data

| Technology | Responsibility |
|---|---|
| Python 3.12+ | Core runtime |
| FastAPI | HTTP API, validation, and SSE |
| Pydantic | Typed contracts and structured model outputs |
| LangChain | Retrieval components, tools, and model adapters |
| LangGraph | Stateful orchestration, parallel branches, retries, checkpoints |
| SQLAlchemy + Alembic | Persistence and migrations |
| PostgreSQL | Relational application and analytics data |
| pgvector | Dense retrieval |
| PostgreSQL full-text search | Lexical retrieval |
| httpx | Async external API clients |
| Pandas or Polars | Deterministic transformations and analysis |

### Frontend

| Technology | Responsibility |
|---|---|
| React + TypeScript | Research interface |
| TanStack Query | Server-state management |
| Server-Sent Events | Streaming agent events |
| Recharts or Vega-Lite | Interactive charts |
| Markdown renderer | Answers with citations |

### Evaluation and observability

| Technology | Responsibility |
|---|---|
| pytest | Unit, integration, trajectory, and regression tests |
| Ragas | RAG and agent metrics |
| DeepEval | LLM test cases and rubric-based evaluation |
| LangSmith | LangChain/LangGraph experiments and annotation |
| Langfuse | Open LLM observability, datasets, and online evaluation |
| Phoenix / OpenInference | Standards-based tracing and evaluator experiments |
| OpenTelemetry | Distributed traces and metrics |

### Infrastructure and quality

| Technology | Responsibility |
|---|---|
| Docker Compose | Local service orchestration |
| Ruff | Linting and formatting |
| Pyright or mypy | Static typing |
| pre-commit | Local quality gates |
| GitHub Actions | CI and evaluation workflows |
| Redis | Optional cache and rate-limit state |

Provider-specific integrations will remain behind internal interfaces.

---

## 🗃 Planned repository structure

```text
company-lens/
├── apps/
│   ├── api/                         # FastAPI application
│   └── web/                         # React application
├── src/company_lens/
│   ├── agents/                      # LangGraph graphs, nodes, and state
│   ├── analytics/                   # Deterministic calculations
│   ├── api/                         # Routes, SSE, dependencies, contracts
│   ├── citations/                   # Evidence registry and validation
│   ├── config/                      # Settings and environment handling
│   ├── context/                     # Context budgets and assembly
│   ├── db/                          # Models, repositories, migrations
│   ├── ingestion/                   # SEC and PDF pipelines
│   ├── llm/                         # Provider-neutral model interfaces
│   ├── observability/               # Traces, logs, metrics, versions
│   ├── retrieval/                   # Dense, lexical, reranking, hierarchy
│   └── tools/                       # SEC, FRED, calculations, internal tools
├── evals/
│   ├── datasets/
│   │   ├── golden/
│   │   ├── synthetic/
│   │   └── production/
│   ├── fixtures/
│   ├── metrics/
│   ├── judges/
│   ├── adapters/
│   │   ├── ragas/
│   │   ├── deepeval/
│   │   ├── langsmith/
│   │   ├── langfuse/
│   │   └── phoenix/
│   ├── runners/
│   └── reports/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── end_to_end/
├── tools/
│   └── data-checks/                  # Standalone source diagnostics
├── docs/
│   ├── architecture/
│   ├── decisions/
│   └── operations/
├── infra/
├── scripts/
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## 🔌 API and interface

Planned endpoints:

```http
POST /api/v1/research
GET  /api/v1/research/{run_id}
GET  /api/v1/research/{run_id}/events
GET  /api/v1/research/{run_id}/sources
POST /api/v1/feedback
GET  /api/v1/companies
GET  /api/v1/health
```

Example streamed event:

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

The UI will show structured execution events, not hidden model reasoning:

```text
✓ Resolved entities: Cloudflare [NET], Datadog [DDOG]
✓ Selected strategy: hybrid structured data + detailed retrieval
✓ Loaded 16 quarterly revenue observations
✓ Retrieved 14 filing passages from 6 documents
✓ Calculated year-over-year growth
✓ Generated chart specification
✓ Validated 9 claim-level citations
```

API delivery is tracked in [#14](https://github.com/zvadym/company-lens/issues/14) and the React interface in [#15](https://github.com/zvadym/company-lens/issues/15).

---

## 🗺 Implementation roadmap

The backlog is dependency-aware. Issue numbers below link to the implementation tasks.

### Phase 0 — Source validation

- [#2 — Data-source availability diagnostics](https://github.com/zvadym/company-lens/issues/2)

### Phase 1 — Foundation and domain model

- [x] [#3 — Backend foundation and local environment](https://github.com/zvadym/company-lens/issues/3)
- [#4 — Hierarchical domain and persistence model](https://github.com/zvadym/company-lens/issues/4)

### Phase 2 — Document ingestion

- [#5 — SEC company and filing ingestion](https://github.com/zvadym/company-lens/issues/5)
- [#6 — PDF ingestion with page provenance](https://github.com/zvadym/company-lens/issues/6)
- [#7 — Section extraction, summaries, and hierarchical chunks](https://github.com/zvadym/company-lens/issues/7)

### Phase 3 — Retrieval and context engineering

- [#8 — Dense, lexical, and hybrid retrieval](https://github.com/zvadym/company-lens/issues/8)
- [#9 — Entity resolution and adaptive hierarchical retrieval](https://github.com/zvadym/company-lens/issues/9)

### Phase 4 — Structured data and deterministic analytics

- [#10 — SEC Company Facts and normalised metrics](https://github.com/zvadym/company-lens/issues/10)
- [#11 — FRED tools, calculations, and chart specifications](https://github.com/zvadym/company-lens/issues/11)

### Phase 5 — Agent and evidence layer

- [#12 — LangGraph research workflow](https://github.com/zvadym/company-lens/issues/12)
- [#13 — Evidence registry and claim-level citation validation](https://github.com/zvadym/company-lens/issues/13)

### Phase 6 — Product interface

- [#14 — FastAPI research API and SSE](https://github.com/zvadym/company-lens/issues/14)
- [#15 — React research interface](https://github.com/zvadym/company-lens/issues/15)

### Phase 7 — Production safeguards and delivery

- [#16 — Observability, reliability, and security](https://github.com/zvadym/company-lens/issues/16)
- [#17 — Deployment and production demo](https://github.com/zvadym/company-lens/issues/17)

### Continuous track — Evaluation Lab

- [#1 — Evaluation framework umbrella](https://github.com/zvadym/company-lens/issues/1)
- [#18 — Canonical golden dataset and human rubric](https://github.com/zvadym/company-lens/issues/18)
- [#19 — Deterministic metrics and CI gates](https://github.com/zvadym/company-lens/issues/19)
- [#20 — LLM-as-a-Judge and calibration](https://github.com/zvadym/company-lens/issues/20)
- [#21 — Multi-framework evaluation adapters](https://github.com/zvadym/company-lens/issues/21)
- [#22 — Online evaluation and production feedback loop](https://github.com/zvadym/company-lens/issues/22)

### Dependency overview

```mermaid
flowchart LR
    I2[#2 Source diagnostics] --> I5[#5 SEC ingestion]
    I2 --> I6[#6 PDF ingestion]
    I2 --> I10[#10 SEC facts]
    I2 --> I11[#11 FRED]

    I3[#3 Foundation] --> I4[#4 Data model]
    I4 --> I5
    I4 --> I6
    I5 --> I7[#7 Hierarchy and chunks]
    I6 --> I7
    I7 --> I8[#8 Hybrid retrieval]
    I8 --> I9[#9 Adaptive retrieval]

    I9 --> I12[#12 LangGraph agent]
    I10 --> I12
    I11 --> I12
    I12 --> I13[#13 Evidence validation]
    I13 --> I14[#14 FastAPI + SSE]
    I14 --> I15[#15 React UI]
    I15 --> I17[#17 Deploy demo]
    I16[#16 Production safeguards] --> I17

    I18[#18 Golden set] --> I19[#19 Deterministic evals]
    I18 --> I20[#20 LLM judges]
    I19 --> I21[#21 Framework adapters]
    I20 --> I21
    I14 --> I22[#22 Online evals]
```

---

## 📏 Quality targets

These are engineering targets, not current benchmark claims.

```yaml
retrieval:
  recall_at_10: 0.90
  precision_at_10: 0.70
  duplicate_rate_max: 0.10

routing:
  accuracy: 0.95
  unnecessary_tool_rate_max: 0.10

citations:
  precision: 0.95
  recall: 0.90

calculations:
  deterministic_fixture_correctness: 1.00

operations:
  first_event_local_ms: 500
  simple_query_p95_seconds: 5
  hybrid_query_p95_seconds: 15
  max_tool_calls_per_run: 10

agent:
  successful_completion_rate: 0.95
  unbounded_loop_rate: 0
```

Thresholds will be adjusted after the first baseline evaluation run.

---

## 🚀 Local development

The backend foundation can be run locally with Docker Compose or directly from a Python virtual environment.

```bash
git clone https://github.com/zvadym/company-lens.git
cd company-lens

cp .env.example .env

# Start PostgreSQL/pgvector and the API
docker compose up --build
```

The API is available at `http://localhost:8000`, and readiness is exposed at:

```bash
curl http://localhost:8000/api/v1/health
```

For local Python development:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

# Apply database migrations
alembic upgrade head

# Run the API without Docker
make run-api

make check
```

Environment variables:

```dotenv
COMPANY_LENS_ENVIRONMENT=local
COMPANY_LENS_LOG_LEVEL=INFO
COMPANY_LENS_DATABASE_URL=postgresql+psycopg://company_lens:company_lens@localhost:5432/company_lens
LLM_PROVIDER=openai
LLM_MODEL=
EMBEDDING_MODEL=
OPENAI_API_KEY=
FRED_API_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=company-lens
```

Do not commit real credentials. Root `.env*` files are ignored except for `.env.example`.

---

## 🧱 Design principles

1. **Use the right data path.** Narrative questions use retrieval; numerical questions use structured data and deterministic calculations.
2. **Resolve exact identifiers before semantic search.** Tickers, CIKs, periods, and filing IDs are not embedding problems.
3. **Retrieve progressively.** Start with the smallest useful representation and expand only when evidence requires it.
4. **Budget context explicitly.** Documents, chunks, tokens, companies, and periods have bounded budgets.
5. **Make orchestration inspectable.** Agent behaviour is represented as typed LangGraph nodes and transitions.
6. **Prefer bounded autonomy.** Tools, loops, retries, and repair attempts have strict limits.
7. **Treat evidence as data.** Claims, citations, calculations, and source lineage are stored and validated.
8. **Evaluate every layer.** Ingestion, retrieval, routing, tools, calculations, claims, latency, and cost have separate metrics.
9. **Calibrate LLM judges.** Model-based scores are compared with human labels and deterministic checks.
10. **Keep integrations replaceable.** Model, evaluation, tracing, and API providers sit behind adapters.
11. **Expose safe execution traces.** Show structured operations, not hidden chain-of-thought.
12. **Fail visibly.** Missing data, conflicting evidence, partial results, and abstention are explicit states.
13. **Version everything that changes behaviour.** Data, parsers, prompts, models, embeddings, indexes, and evaluation sets.
14. **Keep the initial corpus focused.** A small, curated company universe is preferable to a large unreliable corpus.

---

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

---

<div align="center">

Built as a production-oriented demonstration of **adaptive RAG**, **agentic workflows**, **tool calling**, **structured analytics**, **evaluation engineering**, and **observable LLM systems**.

</div>
