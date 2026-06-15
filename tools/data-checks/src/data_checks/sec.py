from __future__ import annotations

import os
from typing import Any

import httpx

from data_checks.http import build_client
from data_checks.models import CheckResult, CompanyConfig


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

REQUIRED_FORMS = ("10-K", "10-Q", "8-K")
FACT_CANDIDATES = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "net_income": ("NetIncomeLoss",),
    "operating_income": ("OperatingIncomeLoss",),
    "assets": ("Assets",),
    "cash_and_equivalents": ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    "research_and_development": ("ResearchAndDevelopmentExpense",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
}


def run_sec_checks(companies: list[CompanyConfig]) -> list[CheckResult]:
    user_agent = os.getenv("SEC_USER_AGENT")
    if not user_agent:
        return [
            CheckResult(
                source="sec",
                check="credentials",
                status="skipped",
                message="SEC_USER_AGENT is not set; SEC checks were skipped.",
            )
        ]

    headers = {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json,text/html,*/*",
    }

    with build_client(headers=headers) as client:
        ticker_result, ticker_map = _load_ticker_map(client)
        results = [ticker_result]
        if ticker_result.status == "failed":
            return results

        for company in companies:
            resolved_cik = ticker_map.get(company.ticker)
            results.append(_check_identity(company, resolved_cik))

            cik = resolved_cik or company.cik
            if not cik:
                results.append(
                    CheckResult(
                        source="sec",
                        check="company",
                        status="failed",
                        company=company.name,
                        ticker=company.ticker,
                        message="No CIK available after ticker lookup.",
                    )
                )
                continue

            results.extend(_check_submissions(client, company, cik))
            results.extend(_check_company_facts(client, company, cik))

    return results


def _load_ticker_map(client: httpx.Client) -> tuple[CheckResult, dict[str, str]]:
    try:
        response = client.get(SEC_TICKERS_URL)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return (
            CheckResult(
                source="sec",
                check="ticker_map",
                status="failed",
                message="Could not load SEC company ticker data.",
                details={"url": SEC_TICKERS_URL, "error": repr(exc)},
            ),
            {},
        )

    ticker_map = {
        str(item["ticker"]).upper(): str(item["cik_str"]).zfill(10)
        for item in payload.values()
        if "ticker" in item and "cik_str" in item
    }
    return (
        CheckResult(
            source="sec",
            check="ticker_map",
            status="passed",
            message=f"Loaded {len(ticker_map)} SEC ticker mappings.",
            details={"url": SEC_TICKERS_URL, "count": len(ticker_map)},
        ),
        ticker_map,
    )


def _check_identity(company: CompanyConfig, resolved_cik: str | None) -> CheckResult:
    configured_cik = company.cik.zfill(10) if company.cik else None
    if not resolved_cik:
        return CheckResult(
            source="sec",
            check="identity",
            status="failed",
            company=company.name,
            ticker=company.ticker,
            message="Ticker was not found in SEC company ticker data.",
            details={"configured_cik": configured_cik},
        )

    if configured_cik and configured_cik != resolved_cik:
        return CheckResult(
            source="sec",
            check="identity",
            status="warning",
            company=company.name,
            ticker=company.ticker,
            message="Configured CIK differs from SEC ticker mapping.",
            details={"configured_cik": configured_cik, "resolved_cik": resolved_cik},
        )

    return CheckResult(
        source="sec",
        check="identity",
        status="passed",
        company=company.name,
        ticker=company.ticker,
        message="Ticker resolved to CIK.",
        details={"resolved_cik": resolved_cik},
    )


def _check_submissions(client: httpx.Client, company: CompanyConfig, cik: str) -> list[CheckResult]:
    padded_cik = cik.zfill(10)
    url = SEC_SUBMISSIONS_URL.format(cik=padded_cik)
    try:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return [
            CheckResult(
                source="sec",
                check="submissions",
                status="failed",
                company=company.name,
                ticker=company.ticker,
                message="Could not load SEC submissions.",
                details={"url": url, "error": repr(exc)},
            )
        ]

    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])

    results: list[CheckResult] = []
    for form in REQUIRED_FORMS:
        latest = _latest_form(form, forms, filing_dates, accession_numbers, primary_documents, padded_cik)
        if latest:
            results.append(
                CheckResult(
                    source="sec",
                    check=f"filing_{form}",
                    status="passed",
                    company=company.name,
                    ticker=company.ticker,
                    message=f"Latest {form} filing found.",
                    details=latest,
                )
            )
        else:
            results.append(
                CheckResult(
                    source="sec",
                    check=f"filing_{form}",
                    status="warning",
                    company=company.name,
                    ticker=company.ticker,
                    message=f"No recent {form} filing found in SEC submissions payload.",
                    details={"url": url},
                )
            )
    return results


def _latest_form(
    target_form: str,
    forms: list[str],
    filing_dates: list[str],
    accession_numbers: list[str],
    primary_documents: list[str],
    padded_cik: str,
) -> dict[str, Any] | None:
    for index, form in enumerate(forms):
        if form != target_form:
            continue
        accession = _safe_get(accession_numbers, index)
        primary_document = _safe_get(primary_documents, index)
        document_url = None
        if accession and primary_document:
            accession_path = accession.replace("-", "")
            document_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{int(padded_cik)}/{accession_path}/{primary_document}"
            )
        return {
            "form": form,
            "filing_date": _safe_get(filing_dates, index),
            "accession_number": accession,
            "primary_document": primary_document,
            "document_url": document_url,
        }
    return None


def _check_company_facts(client: httpx.Client, company: CompanyConfig, cik: str) -> list[CheckResult]:
    padded_cik = cik.zfill(10)
    url = SEC_COMPANY_FACTS_URL.format(cik=padded_cik)
    try:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return [
            CheckResult(
                source="sec",
                check="company_facts",
                status="failed",
                company=company.name,
                ticker=company.ticker,
                message="Could not load SEC Company Facts.",
                details={"url": url, "error": repr(exc)},
            )
        ]

    us_gaap = payload.get("facts", {}).get("us-gaap", {})
    results: list[CheckResult] = []
    for metric, candidates in FACT_CANDIDATES.items():
        concept_name = next((candidate for candidate in candidates if candidate in us_gaap), None)
        if not concept_name:
            results.append(
                CheckResult(
                    source="sec",
                    check=f"fact_{metric}",
                    status="warning",
                    company=company.name,
                    ticker=company.ticker,
                    message=f"No configured US-GAAP concept found for {metric}.",
                    details={"candidates": list(candidates)},
                )
            )
            continue

        latest = _latest_fact(us_gaap[concept_name])
        results.append(
            CheckResult(
                source="sec",
                check=f"fact_{metric}",
                status="passed" if latest else "warning",
                company=company.name,
                ticker=company.ticker,
                message=f"Found SEC Company Facts concept for {metric}."
                if latest
                else f"Found concept for {metric}, but no usable observations.",
                details={
                    "concept": concept_name,
                    "latest": latest,
                },
            )
        )
    return results


def _latest_fact(concept: dict[str, Any]) -> dict[str, Any] | None:
    units = concept.get("units", {})
    observations: list[tuple[str, str, dict[str, Any]]] = []
    for unit, values in units.items():
        for value in values:
            end = value.get("end")
            filed = value.get("filed")
            sort_key = filed or end
            if sort_key:
                observations.append((sort_key, unit, value))

    if not observations:
        return None

    _, unit, value = max(observations, key=lambda item: item[0])
    return {
        "unit": unit,
        "fy": value.get("fy"),
        "fp": value.get("fp"),
        "form": value.get("form"),
        "filed": value.get("filed"),
        "start": value.get("start"),
        "end": value.get("end"),
        "value": value.get("val"),
        "accession_number": value.get("accn"),
    }


def _safe_get(items: list[str], index: int) -> str | None:
    return items[index] if index < len(items) else None
