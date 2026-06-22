from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from company_lens.evidence import (
    AnswerValidator,
    EvidenceEnvelope,
    EvidenceKind,
    EvidenceMetadata,
    EvidenceRegistry,
    SourceStatus,
    citation_metrics,
    extract_claims,
)

CLOUDFLARE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
MICROSOFT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def test_claims_map_inline_citations_at_sentence_level() -> None:
    claims = extract_claims(
        "Revenue was 100 USD [financial_fact:revenue]. Growth was 25 percent [calculation:growth]."
    )

    assert len(claims) == 2
    assert claims[0].evidence_ids == ("financial_fact:revenue",)
    assert claims[1].evidence_ids == ("calculation:growth",)
    assert claims[0].claim_id != claims[1].claim_id


def test_validation_rejects_wrong_company_and_period() -> None:
    registry = EvidenceRegistry(
        (
            _fact(
                "financial_fact:cloudflare",
                company_id=CLOUDFLARE_ID,
                company_name="Cloudflare",
                year=2025,
            ),
            _fact(
                "financial_fact:microsoft",
                company_id=MICROSOFT_ID,
                company_name="Microsoft",
                year=2024,
            ),
        )
    )
    validator = AnswerValidator(registry)

    wrong_company = validator.validate(
        "Microsoft revenue was 100 USD in 2025 [financial_fact:cloudflare]."
    )
    wrong_period = validator.validate(
        "Cloudflare revenue was 100 USD in 2024 [financial_fact:cloudflare]."
    )

    assert wrong_company.valid is False
    assert "wrong_company" in wrong_company.reason_codes
    assert wrong_period.valid is False
    assert "wrong_period" in wrong_period.reason_codes


@pytest.mark.parametrize(
    ("answer", "reason"),
    (
        ("Revenue was 100 USD.", "unsupported_claim"),
        ("Revenue was 100 USD [financial_fact:invented].", "unknown_citations"),
        (
            "Revenue was 999 USD [financial_fact:cloudflare].",
            "unsupported_number",
        ),
    ),
)
def test_validation_rejects_unsupported_material_claims(answer: str, reason: str) -> None:
    validation = AnswerValidator(
        EvidenceRegistry(
            (
                _fact(
                    "financial_fact:cloudflare",
                    company_id=CLOUDFLARE_ID,
                    company_name="Cloudflare",
                    year=2025,
                ),
            )
        )
    ).validate(answer)

    assert validation.valid is False
    assert reason in validation.reason_codes


def test_calculated_claim_requires_complete_input_lineage() -> None:
    fact = _fact(
        "financial_fact:cloudflare",
        company_id=CLOUDFLARE_ID,
        company_name="Cloudflare",
        year=2025,
    )
    calculation = EvidenceEnvelope(
        evidence_id="calculation:growth",
        kind=EvidenceKind.CALCULATION,
        summary="year_over_year_growth: 25 percent",
        source_urls=("https://example.test/fact",),
        lineage_refs=(fact.evidence_id,),
        metadata=EvidenceMetadata(
            operation="year_over_year_growth",
            formula="((current / previous) - 1) * 100",
            unit="percent",
            value=Decimal("25"),
        ),
    )
    valid = AnswerValidator(EvidenceRegistry((fact, calculation))).validate(
        "Revenue growth was 25 percent [calculation:growth]."
    )
    invalid = AnswerValidator(EvidenceRegistry((calculation,))).validate(
        "Revenue growth was 25 percent [calculation:growth]."
    )

    assert valid.valid is True
    assert invalid.valid is False
    assert "incomplete_calculation_lineage" in invalid.reason_codes


def test_optional_semantic_judge_can_reject_superficially_valid_support() -> None:
    fact = _fact(
        "financial_fact:cloudflare",
        company_id=CLOUDFLARE_ID,
        company_name="Cloudflare",
        year=2025,
    )

    validation = AnswerValidator(
        EvidenceRegistry((fact,)), semantic_judge=lambda _claim, _evidence: False
    ).validate("Cloudflare revenue was 100 USD in 2025 [financial_fact:cloudflare].")

    assert validation.valid is False
    assert validation.reason_codes == ("semantic_support_failed",)


def test_source_hydration_reports_exact_pages_and_inaccessible_urls() -> None:
    document = EvidenceEnvelope(
        evidence_id="document:risk",
        kind=EvidenceKind.DOCUMENT,
        summary="Risk factors",
        source_urls=("https://example.test/report.pdf", "not-a-url"),
        lineage_refs=("document:1",),
        metadata=EvidenceMetadata(page_start=12, page_end=13),
    )

    previews = EvidenceRegistry((document,)).hydrate_sources(lambda _url: False)

    assert previews[0].status is SourceStatus.INACCESSIBLE
    assert previews[0].exact_url.endswith("#page=12")
    assert previews[1].status is SourceStatus.INVALID


def test_citation_precision_and_recall_are_computed_per_claim_evidence_link() -> None:
    metrics = citation_metrics(
        {("claim:1", "evidence:1"), ("claim:2", "evidence:wrong")},
        {("claim:1", "evidence:1"), ("claim:2", "evidence:2")},
    )

    assert metrics.precision == 0.5
    assert metrics.recall == 0.5


def _fact(
    evidence_id: str,
    *,
    company_id: uuid.UUID,
    company_name: str,
    year: int,
) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        evidence_id=evidence_id,
        kind=EvidenceKind.FINANCIAL_FACT,
        summary=f"{company_name} revenue: 100 USD at {year}-12-31",
        source_urls=("https://example.test/fact",),
        lineage_refs=("financial_facts",),
        metadata=EvidenceMetadata(
            company_id=company_id,
            company_name=company_name,
            metric="revenue",
            period_end=date(year, 12, 31),
            fiscal_year=year,
            fiscal_period="FY",
            unit="USD",
            value=Decimal("100"),
        ),
    )
