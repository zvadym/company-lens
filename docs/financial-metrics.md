# Canonical financial metrics

CompanyLens stores SEC XBRL observations as structured facts. Narrative retrieval must not be
used to answer deterministic financial-metric questions when a canonical observation exists.

## Mapping contract

The active mapping is [`config/financial_metric_mappings.v1.yaml`](../config/financial_metric_mappings.v1.yaml).
Its `version` is persisted on every observation. Changing the meaning of an existing metric or
adding issuer-specific concepts requires a new mapping version and file.

Initial canonical metric IDs are:

| Metric ID | Meaning |
|---|---|
| `revenue` | Revenue from customers or equivalent total sales |
| `net_income` | Consolidated net income or loss |
| `operating_income` | Operating income or loss |
| `assets` | Total assets at a point in time |
| `cash_and_equivalents` | Cash and cash-equivalent balance |
| `research_and_development_expense` | Research and development expense |
| `operating_cash_flow` | Net cash provided by or used in operating activities |

Global concepts are keyed by XBRL taxonomy and concept name. `company_overrides` can add custom
issuer concepts under a zero-padded CIK. Overrides are additive and must not map one concept to
multiple canonical metrics.

## Period semantics

Every observation has one `period_type`:

- `instant`: a balance measured on one date;
- `quarter`: a duration of approximately one quarter;
- `year_to_date`: a cumulative Q2, Q3, or Q4 duration shorter than a year;
- `annual`: a duration of at least 300 days;
- `other`: a duration that cannot be classified safely.

This distinction prevents a six- or nine-month cumulative SEC fact from being treated as a
standalone quarter.

## Duplicates and restatements

`source_hash` identifies an exact SEC observation, including value, concept, period, form,
filing date, accession number, frame, unit, and mapping version. Exact duplicates are skipped.
Different values for the same canonical metric, period, and unit are retained. Query results mark
those observations with `has_conflict=true`; amended forms are marked with `is_amendment=true`.
Consumers choose the appropriate filing explicitly rather than losing provenance through an
implicit overwrite.

## Commands

```bash
company-lens ingest-company-facts --ticker NET
company-lens ingest-company-facts --all
company-lens query-financial-facts --ticker NET --metric revenue --fiscal-year 2025
```

SEC commands require `COMPANY_LENS_SEC_USER_AGENT`. Raw JSON responses are stored under the
configured SEC artifact root and represented as versioned `sec_company_facts` source documents.

The package-independent query contract is `FinancialFactQueryService`. Agent deployments with
`langchain-core` installed can expose the same contract using
`build_langchain_financial_facts_tool`.
