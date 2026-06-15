# CompanyLens Data Source Checks

Standalone diagnostics for checking whether the planned CompanyLens MVP data
sources are reachable and usable.

This directory is intentionally isolated from the main project code. The scripts
do not import from the future application package.

## Setup

```bash
cd tools/data-checks
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment

SEC automated requests should include an identifying user agent.

```bash
export SEC_USER_AGENT="CompanyLens data checks your-email@example.com"
```

FRED checks require an API key.

```bash
export FRED_API_KEY="..."
```

Missing credentials do not stop the whole run. The affected checks are marked as
`skipped` in the console summary and JSON report.

## Run

```bash
python -m data_checks run-all
```

The command runs:

- SEC ticker-to-CIK resolution
- SEC submissions availability
- SEC Company Facts availability
- FRED macro series availability
- PDF URL download and basic extraction checks

Reports are written to `reports/data-checks-<timestamp>.json`.

## Config

- `config/companies.yaml` defines the company universe and PDF URL manifest.
- `config/fred_series.yaml` defines the macroeconomic series to check.

PDF checks are manifest-only in this version. The scripts do not crawl investor
relations pages.
