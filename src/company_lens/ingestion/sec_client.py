from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from time import monotonic, sleep
from typing import Any

import httpx

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_ARCHIVE_BASE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_path}"


class SecClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecCompany:
    ticker: str
    cik: str
    name: str


@dataclass(frozen=True)
class SecDocument:
    document_name: str
    document_type: str
    source_url: str
    size_bytes: int | None = None


@dataclass(frozen=True)
class SecFilingMetadata:
    cik: str
    company_name: str
    form_type: str
    accession_number: str
    filing_date: date | None
    report_date: date | None
    primary_document: str
    source_url: str
    source_index_url: str
    metadata: dict[str, Any]


class RateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self._minimum_interval = 0.0 if requests_per_second <= 0 else 1.0 / requests_per_second
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self._minimum_interval == 0.0:
            return
        now = monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self._minimum_interval - elapsed
            if remaining > 0:
                sleep(remaining)
        self._last_request_at = monotonic()


class SecClient:
    def __init__(
        self,
        user_agent: str,
        *,
        timeout_seconds: float = 30.0,
        retry_attempts: int = 3,
        rate_limit_per_second: float = 9.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("SEC user agent must be provided.")
        self._retry_attempts = max(1, retry_attempts)
        self._rate_limiter = RateLimiter(rate_limit_per_second)
        self._client = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json,text/html,text/plain,*/*",
            },
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SecClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch_ticker_map(self) -> dict[str, SecCompany]:
        payload = self.get_json(SEC_TICKERS_URL)
        companies: dict[str, SecCompany] = {}
        for item in payload.values():
            ticker = str(item["ticker"]).upper()
            cik = str(item["cik_str"]).zfill(10)
            companies[ticker] = SecCompany(ticker=ticker, cik=cik, name=str(item["title"]))
        return companies

    def resolve_ticker(self, ticker: str) -> SecCompany:
        ticker_map = self.fetch_ticker_map()
        normalized_ticker = ticker.upper()
        try:
            return ticker_map[normalized_ticker]
        except KeyError as exc:
            raise SecClientError(f"Ticker {normalized_ticker} was not found in SEC data.") from exc

    def fetch_submissions(self, cik: str) -> dict[str, Any]:
        return self.get_json(SEC_SUBMISSIONS_URL.format(cik=cik.zfill(10)))

    def fetch_company_facts(self, cik: str) -> dict[str, Any]:
        return self.get_json(SEC_COMPANY_FACTS_URL.format(cik=cik.zfill(10)))

    def iter_recent_filings(
        self,
        cik: str,
        company_name: str,
        submissions: dict[str, Any],
        *,
        forms: Iterable[str],
        limit_per_form: int,
    ) -> list[SecFilingMetadata]:
        selected_forms = {form.upper() for form in forms}
        remaining_by_form = {form: limit_per_form for form in selected_forms}
        recent = submissions.get("filings", {}).get("recent", {})
        rows = self._recent_rows(recent)
        filings: list[SecFilingMetadata] = []

        for row in rows:
            form_type = str(row.get("form") or "").upper()
            if form_type not in selected_forms or remaining_by_form[form_type] <= 0:
                continue
            accession_number = str(row.get("accessionNumber") or "")
            primary_document = str(row.get("primaryDocument") or "")
            if not accession_number or not primary_document:
                continue
            source_url, source_index_url = build_filing_urls(
                cik, accession_number, primary_document
            )
            filings.append(
                SecFilingMetadata(
                    cik=cik.zfill(10),
                    company_name=company_name,
                    form_type=form_type,
                    accession_number=accession_number,
                    filing_date=_parse_date(row.get("filingDate")),
                    report_date=_parse_date(row.get("reportDate")),
                    primary_document=primary_document,
                    source_url=source_url,
                    source_index_url=source_index_url,
                    metadata=row,
                )
            )
            remaining_by_form[form_type] -= 1
            if all(remaining <= 0 for remaining in remaining_by_form.values()):
                break

        return filings

    def fetch_archive_documents(self, cik: str, accession_number: str) -> list[SecDocument]:
        index_url = build_archive_index_url(cik, accession_number)
        payload = self.get_json(index_url)
        items = payload.get("directory", {}).get("item", [])
        base_url = archive_base_url(cik, accession_number)
        documents: list[SecDocument] = []
        for item in items:
            name = str(item.get("name") or "")
            if not name:
                continue
            documents.append(
                SecDocument(
                    document_name=name,
                    document_type=str(item.get("type") or ""),
                    source_url=f"{base_url}/{name}",
                    size_bytes=_parse_int(item.get("size")),
                )
            )
        return documents

    def get_bytes(self, url: str) -> tuple[bytes, str | None]:
        response = self._request("GET", url)
        return response.content, response.headers.get("content-type")

    def get_json(self, url: str) -> dict[str, Any]:
        response = self._request("GET", url)
        payload = response.json()
        if not isinstance(payload, dict):
            raise SecClientError(f"SEC endpoint returned non-object JSON: {url}")
        return payload

    def _request(self, method: str, url: str) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self._retry_attempts + 1):
            self._rate_limiter.wait()
            try:
                response = self._client.request(method, url)
                response.raise_for_status()
                return response
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_error = exc
                if attempt == self._retry_attempts:
                    break
                sleep(min(2.0, 0.25 * attempt))
        raise SecClientError(f"SEC request failed for {url}: {last_error!r}")

    @staticmethod
    def _recent_rows(recent: Mapping[str, Any]) -> list[dict[str, Any]]:
        row_count = max(
            (len(value) for value in recent.values() if isinstance(value, list)),
            default=0,
        )
        rows: list[dict[str, Any]] = []
        for index in range(row_count):
            row: dict[str, Any] = {}
            for key, values in recent.items():
                if isinstance(values, list) and index < len(values):
                    row[key] = values[index]
            rows.append(row)
        return rows


def archive_base_url(cik: str, accession_number: str) -> str:
    return SEC_ARCHIVE_BASE_URL.format(
        cik_int=int(cik),
        accession_path=accession_number.replace("-", ""),
    )


def build_archive_index_url(cik: str, accession_number: str) -> str:
    return f"{archive_base_url(cik, accession_number)}/index.json"


def build_filing_urls(cik: str, accession_number: str, primary_document: str) -> tuple[str, str]:
    base_url = archive_base_url(cik, accession_number)
    return f"{base_url}/{primary_document}", f"{base_url}/{accession_number}.txt"


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None
