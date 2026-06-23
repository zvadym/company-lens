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
    SemanticSupportResult,
    SemanticSupportStatus,
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


def test_claims_attach_citations_written_after_sentence_punctuation() -> None:
    claims = extract_claims(
        "Revenue grew by 25 percent. [calculation:growth] Margin improved. [financial_fact:margin]"
    )

    assert len(claims) == 2
    assert claims[0].text == "Revenue grew by 25 percent."
    assert claims[0].evidence_ids == ("calculation:growth",)
    assert claims[1].text == "Margin improved."
    assert claims[1].evidence_ids == ("financial_fact:margin",)


def test_validation_accepts_citation_block_after_terminal_period() -> None:
    fact = _fact(
        "financial_fact:cloudflare",
        company_id=CLOUDFLARE_ID,
        company_name="Cloudflare",
        year=2025,
    )

    validation = AnswerValidator(EvidenceRegistry((fact,))).validate(
        "Cloudflare revenue was 100 USD in 2025. [financial_fact:cloudflare]"
    )

    assert validation.valid is True
    assert validation.claims[0].evidence_ids == ("financial_fact:cloudflare",)


def test_claims_parse_markdown_table_rows_without_structural_claims() -> None:
    claims = extract_claims(
        """## Revenue growth

| Year | Revenue | YoY growth | Evidence |
|---|---:|---:|---|
| 2023 | $1.297 billion | 33.0% vs. 2022 | [financial_fact:2023] |
| 2024 | $1.670 billion | 28.8% vs. 2023 | [financial_fact:2024] |
| 2025 | $2.168 billion | 29.8% vs. 2024 | [calculation:growth] |
"""
    )

    assert len(claims) == 3
    assert [claim.evidence_ids for claim in claims] == [
        ("financial_fact:2023",),
        ("financial_fact:2024",),
        ("calculation:growth",),
    ]
    assert all("vs." in claim.text for claim in claims)


def test_filing_form_is_not_treated_as_an_unsupported_number() -> None:
    fact = _fact(
        "financial_fact:cloudflare",
        company_id=CLOUDFLARE_ID,
        company_name="Cloudflare",
        year=2025,
    )

    validation = AnswerValidator(EvidenceRegistry((fact,))).validate(
        "Cloudflare reported 100 USD in its 2025 Form 10-K [financial_fact:cloudflare]."
    )

    assert validation.valid is True


@pytest.mark.parametrize(
    "answer",
    (
        (
            "Коротко по суті: у розділі **Item 1. Business / Overview** Cloudflare "
            "формулює свою місію як “help build a better Internet” [document:business]."
        ),
        ("У **Item 1A. Risk Factors** Cloudflare описує material risks [document:business]."),
        ("У Item 7. Management Discussion компанія пояснює результати [document:business]."),
        "Part I. Business describes Cloudflare's operations [document:business].",
        "Part II. Other Information covers later filing content [document:business].",
    ),
)
def test_sec_section_labels_do_not_create_unsupported_claim_fragments(answer: str) -> None:
    claims = extract_claims(answer)
    document = EvidenceEnvelope(
        evidence_id="document:business",
        kind=EvidenceKind.DOCUMENT,
        summary="Cloudflare business overview and report sections",
        source_urls=("https://example.test/report",),
        metadata=EvidenceMetadata(company_id=CLOUDFLARE_ID, company_name="Cloudflare"),
    )
    validation = AnswerValidator(EvidenceRegistry((document,))).validate(answer)

    assert len(claims) == 1
    assert claims[0].evidence_ids == ("document:business",)
    assert "Item 1." not in claims[0].text or "Business" in claims[0].text
    assert validation.valid is True


def test_real_unsupported_claim_still_requires_a_citation() -> None:
    validation = AnswerValidator(EvidenceRegistry(())).validate("Revenue was 100 USD.")

    assert validation.valid is False
    assert validation.reason_codes == ("unsupported_claim",)


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


def test_calculation_formula_constants_and_company_metadata_support_claim() -> None:
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
            company_id=CLOUDFLARE_ID,
            company_name="Cloudflare",
            metric="revenue",
            operation="year_over_year_growth",
            formula="(current / prior_year - 1) * 100",
            unit="percent",
            value=Decimal("25"),
        ),
    )

    validation = AnswerValidator(EvidenceRegistry((fact, calculation))).validate(
        "Cloudflare revenue growth uses (current / prior year - 1) times 100 [calculation:growth]."
    )

    assert validation.valid is True


def test_validation_accepts_rounded_percentages_and_scaled_financial_values() -> None:
    previous = _fact(
        "financial_fact:previous",
        company_id=CLOUDFLARE_ID,
        company_name="Cloudflare",
        year=2024,
    ).model_copy(
        update={
            "metadata": EvidenceMetadata(
                company_id=CLOUDFLARE_ID,
                company_name="Cloudflare",
                metric="revenue",
                period_end=date(2024, 12, 31),
                fiscal_year=2024,
                fiscal_period="FY",
                unit="USD",
                value=Decimal("1669626000"),
            )
        }
    )
    current = _fact(
        "financial_fact:current",
        company_id=CLOUDFLARE_ID,
        company_name="Cloudflare",
        year=2025,
    ).model_copy(
        update={
            "metadata": EvidenceMetadata(
                company_id=CLOUDFLARE_ID,
                company_name="Cloudflare",
                metric="revenue",
                period_end=date(2025, 12, 31),
                fiscal_year=2025,
                fiscal_period="FY",
                unit="USD",
                value=Decimal("2167937000"),
            )
        }
    )
    calculation = EvidenceEnvelope(
        evidence_id="calculation:growth",
        kind=EvidenceKind.CALCULATION,
        summary="year_over_year_growth: 29.845666035387565838 percent",
        source_urls=("https://example.test/fact",),
        lineage_refs=(previous.evidence_id, current.evidence_id),
        metadata=EvidenceMetadata(
            operation="year_over_year_growth",
            formula="(current / previous - 1) * 100",
            unit="percent",
            value=Decimal("29.845666035387565838"),
        ),
        payload={
            "values": [{"value": "29.845666035387565838"}],
            "inputs": [{"value": "1669626000"}, {"value": "2167937000"}],
        },
    )
    answer = (
        "Cloudflare revenue growth was 29.85% year over year "
        "[calculation:growth], based on revenue rising from $1.670 billion in 2024 "
        "[financial_fact:previous] to $2.168 billion in 2025 [financial_fact:current]."
    )

    validation = AnswerValidator(EvidenceRegistry((previous, current, calculation))).validate(
        answer
    )

    assert validation.valid is True
    assert validation.reason_codes == ()


def test_optional_semantic_judge_can_reject_superficially_valid_support() -> None:
    fact = _fact(
        "financial_fact:cloudflare",
        company_id=CLOUDFLARE_ID,
        company_name="Cloudflare",
        year=2025,
    )

    validation = AnswerValidator(
        EvidenceRegistry((fact,)),
        semantic_judge=lambda _claim, _evidence: SemanticSupportResult(
            status=SemanticSupportStatus.UNSUPPORTED,
            reason_code="evidence_does_not_entail_claim",
            prompt_version="test.v1",
        ),
    ).validate("Cloudflare revenue was 100 USD in 2025 [financial_fact:cloudflare].")

    assert validation.valid is False
    assert validation.reason_codes == ("semantic_support_failed",)


def test_unavailable_semantic_judge_is_distinct_from_unsupported_claim() -> None:
    fact = _fact(
        "financial_fact:cloudflare",
        company_id=CLOUDFLARE_ID,
        company_name="Cloudflare",
        year=2025,
    )

    validation = AnswerValidator(
        EvidenceRegistry((fact,)),
        semantic_judge=lambda _claim, _evidence: SemanticSupportResult(
            status=SemanticSupportStatus.UNAVAILABLE,
            reason_code="provider_timeout",
            prompt_version="test.v1",
        ),
    ).validate("Cloudflare revenue was 100 USD in 2025 [financial_fact:cloudflare].")

    assert validation.valid is True
    assert validation.claims[0].semantic_support is not None
    assert validation.claims[0].semantic_support.status is SemanticSupportStatus.UNAVAILABLE


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
