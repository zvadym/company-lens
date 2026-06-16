from __future__ import annotations

import httpx

from company_lens.ingestion.sec_client import SEC_SUBMISSIONS_URL, SEC_TICKERS_URL, SecClient


def test_sec_client_resolves_ticker_and_builds_recent_filing_metadata() -> None:
    cik = "0001477333"
    accession = "0001477333-26-000001"
    primary_document = "net-20251231.htm"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == SEC_TICKERS_URL:
            return httpx.Response(
                200,
                json={
                    "0": {
                        "ticker": "NET",
                        "cik_str": 1477333,
                        "title": "Cloudflare, Inc.",
                    }
                },
            )
        if str(request.url) == SEC_SUBMISSIONS_URL.format(cik=cik):
            return httpx.Response(
                200,
                json={
                    "filings": {
                        "recent": {
                            "form": ["10-K", "8-K"],
                            "accessionNumber": [accession, "0001477333-26-000002"],
                            "filingDate": ["2026-02-20", "2026-03-01"],
                            "reportDate": ["2025-12-31", "2026-03-01"],
                            "primaryDocument": [primary_document, "net-8k.htm"],
                        }
                    }
                },
            )
        return httpx.Response(404)

    with SecClient(
        "CompanyLens tests@example.com",
        transport=httpx.MockTransport(handler),
        rate_limit_per_second=0,
    ) as client:
        company = client.resolve_ticker("net")
        submissions = client.fetch_submissions(company.cik)
        filings = client.iter_recent_filings(
            company.cik,
            company.name,
            submissions,
            forms=("10-K", "10-Q"),
            limit_per_form=1,
        )

    assert company.cik == cik
    assert company.name == "Cloudflare, Inc."
    assert len(filings) == 1
    assert filings[0].source_url == (
        "https://www.sec.gov/Archives/edgar/data/1477333/000147733326000001/net-20251231.htm"
    )
    assert filings[0].source_index_url == (
        "https://www.sec.gov/Archives/edgar/data/"
        "1477333/000147733326000001/0001477333-26-000001.txt"
    )
