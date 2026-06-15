from __future__ import annotations

from data_checks.config import REPORTS_DIR, load_companies, load_fred_series
from data_checks.fred import run_fred_checks
from data_checks.pdf import run_pdf_checks
from data_checks.report import build_report, print_summary, write_report
from data_checks.sec import run_sec_checks


def run_all() -> int:
    companies = load_companies()
    fred_series = load_fred_series()

    results = []
    results.extend(run_sec_checks(companies))
    results.extend(run_fred_checks(fred_series))
    results.extend(run_pdf_checks(companies))

    report = build_report(results)
    path = write_report(report, REPORTS_DIR)
    print_summary(report, path)

    return 1 if report["summary"]["failed"] else 0
