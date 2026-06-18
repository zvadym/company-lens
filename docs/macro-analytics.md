# FRED macro data and deterministic analytics

Issue #11 adds a revision-aware FRED cache, Decimal calculations, and provider-neutral chart
specifications.

## Live FRED workflow

Set `FRED_API_KEY` (or `COMPANY_LENS_FRED_API_KEY`), apply migrations, and ingest one or more
series:

```bash
alembic upgrade head
company-lens ingest-fred \
  --series FEDFUNDS \
  --observation-start 2025-01-01 \
  --observation-end 2025-12-31
```

The ingest command stores series metadata, observations, missing-value markers, revision dates,
units, frequency, and source URLs. Repeating the command is idempotent.

Query only the cached database; this command does not call FRED:

```bash
company-lens query-fred \
  --series FEDFUNDS \
  --observation-start 2025-01-01 \
  --observation-end 2025-12-31
```

Use `--include-missing` to include observations whose FRED value is `.`.

## Calculation guarantees

Calculations use Python `Decimal` with 28 significant digits. Every result contains its inputs,
formula, output unit, source URLs, and precision policy. Missing values, zero denominators, and
incompatible units fail explicitly. Correlation results always include a non-causation warning.

Supported operations are quarter-over-quarter growth, year-over-year growth, CAGR, margin,
absolute change, percentage change, rolling average, normalised index, and correlation.

Chart specifications can only be generated from `ValidatedChartDataset`. Validation requires
declared fields and units, complete rows, unique ascending dates, labels, and source lineage.
