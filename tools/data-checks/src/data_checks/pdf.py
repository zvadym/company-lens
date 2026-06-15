from __future__ import annotations

import hashlib
import logging
from io import BytesIO

import httpx
from pypdf import PdfReader

from data_checks.http import build_client
from data_checks.models import CheckResult, CompanyConfig, PdfConfig


PDF_MAX_BYTES = 50 * 1024 * 1024
TEXT_SAMPLE_PAGES = 3

logging.getLogger("pypdf").setLevel(logging.ERROR)


def run_pdf_checks(companies: list[CompanyConfig]) -> list[CheckResult]:
    results: list[CheckResult] = []
    headers = {"User-Agent": "CompanyLens data checks"}
    with build_client(headers=headers) as client:
        for company in companies:
            if not company.pdfs:
                results.append(
                    CheckResult(
                        source="pdf",
                        check="manifest",
                        status="warning",
                        company=company.name,
                        ticker=company.ticker,
                        message="No PDF URLs are configured for this company.",
                    )
                )
                continue

            for pdf in company.pdfs:
                results.append(_check_pdf(client, company, pdf))
    return results


def _check_pdf(client: httpx.Client, company: CompanyConfig, pdf: PdfConfig) -> CheckResult:
    try:
        with client.stream("GET", pdf.url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            content_length = response.headers.get("content-length")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > PDF_MAX_BYTES:
                    return CheckResult(
                        source="pdf",
                        check="download",
                        status="failed",
                        company=company.name,
                        ticker=company.ticker,
                        message="PDF exceeded maximum diagnostic download size.",
                        details=_pdf_base_details(pdf, content_type, content_length)
                        | {"max_bytes": PDF_MAX_BYTES, "downloaded_bytes": total},
                    )
                chunks.append(chunk)
    except Exception as exc:
        return CheckResult(
            source="pdf",
            check="download",
            status="failed",
            company=company.name,
            ticker=company.ticker,
            message="Could not download PDF URL.",
            details=_pdf_base_details(pdf) | {"error": repr(exc)},
        )

    content = b"".join(chunks)
    sha256 = hashlib.sha256(content).hexdigest()
    content_type_warning = "pdf" not in content_type.lower()

    try:
        reader = PdfReader(BytesIO(content))
        page_count = len(reader.pages)
        sample_text = _extract_sample_text(reader)
    except Exception as exc:
        return CheckResult(
            source="pdf",
            check="extract",
            status="failed",
            company=company.name,
            ticker=company.ticker,
            message="Downloaded file could not be parsed as a PDF.",
            details=_pdf_base_details(pdf, content_type, content_length)
            | {
                "downloaded_bytes": len(content),
                "sha256": sha256,
                "error": repr(exc),
            },
        )

    has_text = bool(sample_text.strip())
    if content_type_warning or not has_text:
        status = "warning"
        message = "PDF downloaded, but content type or text extraction needs review."
    else:
        status = "passed"
        message = "PDF downloaded and basic text extraction succeeded."

    return CheckResult(
        source="pdf",
        check="download_extract",
        status=status,
        company=company.name,
        ticker=company.ticker,
        message=message,
        details=_pdf_base_details(pdf, content_type, content_length)
        | {
            "downloaded_bytes": len(content),
            "sha256": sha256,
            "page_count": page_count,
            "sample_text_characters": len(sample_text),
            "sample_text_preview": sample_text[:500],
        },
    )


def _extract_sample_text(reader: PdfReader) -> str:
    texts: list[str] = []
    for page in reader.pages[:TEXT_SAMPLE_PAGES]:
        texts.append(page.extract_text() or "")
    return "\n".join(texts)


def _pdf_base_details(
    pdf: PdfConfig,
    content_type: str | None = None,
    content_length: str | None = None,
) -> dict[str, str | None]:
    return {
        "label": pdf.label,
        "type": pdf.type,
        "url": pdf.url,
        "content_type": content_type,
        "content_length": content_length,
    }
