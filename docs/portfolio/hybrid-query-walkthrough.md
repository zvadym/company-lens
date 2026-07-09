# Hybrid Query Walkthrough

This walkthrough uses one portfolio-style question to show how CompanyLens combines structured
facts, document retrieval, macro data, calculations, charts, and citation validation.

> Compare Cloudflare, Datadog, and MongoDB revenue growth over the last eight quarters.
> Identify the two most frequently reported business risks for each company, explain whether
> management's outlook changed, and plot revenue growth against the federal funds rate.

This is a hybrid query. It asks for numbers, narrative risk evidence, outlook language, and a macro
comparison in one answer.

## What The Agent Adds

The user gives a natural-language request. The graph turns it into typed state:

| Added state | Example |
|---|---|
| Companies | Cloudflare, Datadog, MongoDB |
| Metrics | `revenue`, revenue growth |
| Period intent | last eight quarters |
| Narrative sections | risk factors, business outlook, MD&A-style management discussion |
| Macro series | federal funds rate |
| Required capabilities | document retrieval, financial facts, macro series, calculations, chart generation, citations |
| Evidence and artifacts | `financial_fact:*`, `chunk:*`, `macro:*`, and `calculation:*` evidence IDs, plus a chart artifact |

The exact company IDs, accession numbers, fiscal periods, and source URLs come from entity
resolution and source preparation. The model does not invent those identifiers.

## What Runs

| Stage | Graph node or tool | What happens |
|---|---|---|
| Parse | `parse_question` | Classifies the request as hybrid and extracts chart, metric, comparison, and follow-up signals. |
| Resolve | `resolve_entities` | Resolves company mentions, known metric aliases, reporting periods, and macro series. |
| Prepare | `prepare_company_data` -> `prepare_companies` | Ensures filings, chunks, embeddings, and structured facts are available for the requested companies. |
| Plan | `plan_request` | Builds a typed plan with document, financial, macro, calculation, and chart branches. |
| Retrieve | `retrieve_documents` | Uses adaptive retrieval for risk/outlook evidence, including exact filters and optional reranking. |
| Facts | `query_financial_facts` | Pulls quarterly revenue observations from structured SEC Company Facts tables. |
| Macro | `query_macro_series` | Pulls federal funds rate observations from FRED-backed storage. |
| Calculate | `calculate_metrics` | Computes revenue growth from typed observations. |
| Chart | `generate_chart_spec` | Builds a chart spec from validated numeric datasets. |
| Evidence | `merge_evidence` | Converts all source results into compact evidence envelopes with IDs and lineage. |
| Answer | `generate_answer` | Writes a grounded draft from the evidence context. |
| Validate | `validate_citations` | Checks citations, companies, periods, units, unsupported numbers, and calculation lineage. |
| Repair | `repair_or_abstain` | Repairs invalid citation usage or returns a safe abstention if validation cannot pass. |

## Example Plan Shape

The actual plan is validated Pydantic state, but conceptually it looks like this:

```json
{
  "route": "hybrid",
  "requires_citations": true,
  "branches": [
    {
      "kind": "query_financial_facts",
      "branch_id": "revenue_facts",
      "metric": "revenue",
      "companies": ["Cloudflare", "Datadog", "MongoDB"],
      "periods": "last eight quarters"
    },
    {
      "kind": "retrieve_documents",
      "branch_id": "risk_outlook_docs",
      "strategy": "hybrid",
      "sections": ["risk_factors", "business", "management_discussion"]
    },
    {
      "kind": "query_macro_series",
      "branch_id": "fed_funds",
      "series": ["FEDFUNDS"]
    },
    {
      "kind": "calculate_metrics",
      "branch_id": "revenue_growth",
      "operation": "quarter_over_quarter_growth",
      "depends_on": ["revenue_facts"]
    },
    {
      "kind": "generate_chart_spec",
      "branch_id": "growth_vs_rates_chart",
      "depends_on": ["revenue_growth", "fed_funds"]
    }
  ]
}
```

## Example Retrieval Trace

This is a representative trace, not a captured production run. It shows the kind of ordering change
the reranker is designed to make.

First-stage retrieval finds candidates with dense vector search, lexical search, and hybrid RRF.
Some candidates are generally similar to the query, but not all are equally useful for the final
answer.

| First-stage rank | Candidate | Why it matched |
|---:|---|---|
| 1 | Cloudflare 10-K, risk factors, competition paragraph | Strong keyword overlap with "business risks". |
| 2 | Datadog 10-Q, revenue table context | Similar to "revenue growth" but weak for risk explanation. |
| 3 | MongoDB 10-K, macroeconomic uncertainty risk | Directly useful for risk discussion. |
| 4 | Cloudflare 10-Q, liquidity section | Mentions outlook, but less central to the question. |
| 5 | Datadog 10-K, customer concentration and sales cycle risk | Directly useful for risk discussion. |

With HTTP reranking enabled, the candidate text is rescored against the query before final evidence
selection:

| Reranked rank | Candidate | Why it moved |
|---:|---|---|
| 1 | Datadog 10-K, customer concentration and sales cycle risk | Directly answers the "reported business risks" part. |
| 2 | MongoDB 10-K, macroeconomic uncertainty risk | Strong support for risk and outlook language. |
| 3 | Cloudflare 10-K, risk factors, competition paragraph | Still relevant and keeps company coverage balanced. |
| 4 | Cloudflare 10-Q, liquidity section | Useful as secondary outlook evidence. |
| 5 | Datadog 10-Q, revenue table context | Better handled by structured facts, so it falls behind narrative evidence. |

After reranking, the backend still applies duplicate removal, document/period diversity, and final
top-k selection. Reranking improves ordering; it does not bypass source lineage or citation checks.

## What The Model Sees

Answer generation receives compact evidence records, not unrestricted database rows:

```json
[
  {
    "evidence_id": "financial_fact:cloudflare-revenue-2025-q2",
    "kind": "financial_fact",
    "summary": "Cloudflare revenue for 2025 Q2...",
    "metadata": {
      "company_name": "Cloudflare",
      "metric": "revenue",
      "unit": "USD"
    }
  },
  {
    "evidence_id": "chunk:datadog-risk-sales-cycle",
    "kind": "document",
    "summary": "Datadog describes sales cycle and customer adoption risks...",
    "metadata": {
      "company_name": "Datadog",
      "filing_form": "10-K",
      "section": "risk_factors"
    }
  },
  {
    "evidence_id": "calculation:mongodb-revenue-growth",
    "kind": "calculation",
    "summary": "Quarter-over-quarter revenue growth...",
    "lineage_refs": [
      "financial_fact:mongodb-revenue-previous-quarter",
      "financial_fact:mongodb-revenue-current-quarter"
    ]
  }
]
```

The draft must cite those IDs. If it says a company grew revenue by a specific percentage, the
validator checks that the cited calculation exists and that its input facts have the right company,
period, unit, and formula lineage.

## What The Reader Should Notice

The point is not just that the answer uses an LLM. The engineering value is in the boundaries:

- text evidence and numeric facts are fetched through different paths;
- the graph can run independent branches in parallel;
- retrieval candidates can be reranked without losing citation metadata;
- chart data comes from validated numeric datasets;
- public traces explain actions without exposing private reasoning or raw payloads;
- final answers must pass citation validation before they are shown as completed.

## Reference Docs

- [Research graph](research-graph.md)
- [Retrieval and reranking](retrieval-and-reranking.md)
- [Financial metrics mapping](../financial-metrics.md)
- [Macro analytics](../macro-analytics.md)
