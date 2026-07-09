from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal, cast

from pydantic import BaseModel

from company_lens.agent import (
    ModelMessage,
    ModelPurpose,
    ModelSemanticSupportJudge,
    SemanticSupportJudgment,
    StructuredModelResult,
    TextModelResult,
)
from company_lens.evidence import (
    ClaimRecord,
    EvidenceEnvelope,
    EvidenceKind,
    SemanticSupportStatus,
    ValidationIssue,
)


class JudgeProvider:
    def __init__(
        self,
        *,
        verdict: Literal["supported", "unsupported"] = "supported",
        refusal: bool = False,
        resolved_issue_codes: tuple[str, ...] = (),
    ) -> None:
        self.verdict = verdict
        self.refusal = refusal
        self.resolved_issue_codes = resolved_issue_codes
        self.calls: list[tuple[ModelPurpose, tuple[ModelMessage, ...]]] = []

    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        assert purpose is ModelPurpose.VALIDATE
        assert output_type is SemanticSupportJudgment
        self.calls.append((purpose, tuple(messages)))
        if self.refusal:
            return StructuredModelResult(
                model="judge",
                response_id="response-1",
                refusal="Cannot judge.",
            )
        judgment = SemanticSupportJudgment(
            verdict=self.verdict,
            reason_code=(
                "direct_support" if self.verdict == "supported" else "evidence_not_entailing"
            ),
            resolved_issue_codes=self.resolved_issue_codes,
        )
        return StructuredModelResult(
            model="judge",
            response_id="response-1",
            output=cast(OutputT, judgment),
        )

    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult:
        raise AssertionError("Text generation is not used by the semantic judge.")


def test_model_semantic_support_judge_uses_structured_validation_purpose() -> None:
    claim = ClaimRecord(
        claim_id="claim:1111111111111111",
        text="Competition is a risk.",
        evidence_ids=("document:risk",),
        sentence_index=0,
    )
    evidence = EvidenceEnvelope(
        evidence_id="document:risk",
        kind=EvidenceKind.DOCUMENT,
        summary="Competition is a material business risk.",
        source_urls=("https://example.test/risk",),
        lineage_refs=("risk",),
    )

    result = ModelSemanticSupportJudge(JudgeProvider())(claim, (evidence,))

    assert result.status is SemanticSupportStatus.SUPPORTED
    assert result.reason_code == "direct_support"
    assert result.model == "judge"


def test_model_semantic_support_judge_skips_structured_evidence() -> None:
    claim = ClaimRecord(
        claim_id="claim:2222222222222222",
        text="Revenue was 100 USD.",
        evidence_ids=("financial_fact:revenue",),
        sentence_index=0,
    )
    evidence = EvidenceEnvelope(
        evidence_id="financial_fact:revenue",
        kind=EvidenceKind.FINANCIAL_FACT,
        summary="Revenue was 100 USD.",
        source_urls=("https://example.test/revenue",),
        lineage_refs=("financial",),
    )

    result = ModelSemanticSupportJudge(JudgeProvider())(claim, (evidence,))

    assert result.status is SemanticSupportStatus.NOT_RUN
    assert result.reason_code == "deterministic_validation_sufficient"


def test_model_semantic_support_judge_distinguishes_unsupported_and_unavailable() -> None:
    claim = ClaimRecord(
        claim_id="claim:3333333333333333",
        text="Competition caused the revenue decline.",
        evidence_ids=("document:risk",),
        sentence_index=0,
    )
    evidence = EvidenceEnvelope(
        evidence_id="document:risk",
        kind=EvidenceKind.DOCUMENT,
        summary="Competition is a material business risk.",
        source_urls=("https://example.test/risk",),
        lineage_refs=("risk",),
    )

    unsupported = ModelSemanticSupportJudge(JudgeProvider(verdict="unsupported"))(
        claim, (evidence,)
    )
    unavailable = ModelSemanticSupportJudge(JudgeProvider(refusal=True))(claim, (evidence,))

    assert unsupported.status is SemanticSupportStatus.UNSUPPORTED
    assert unavailable.status is SemanticSupportStatus.UNAVAILABLE
    assert unavailable.reason_code == "semantic_judge_refusal"


def test_model_semantic_support_judge_passes_validation_issues() -> None:
    claim = ClaimRecord(
        claim_id="claim:4444444444444444",
        text="The annual report period was 2024.",
        evidence_ids=("document:risk",),
        sentence_index=0,
    )
    evidence = EvidenceEnvelope(
        evidence_id="document:risk",
        kind=EvidenceKind.DOCUMENT,
        summary="The cited filing refers to the annual report for the year ended 2024.",
        source_urls=("https://example.test/risk",),
        lineage_refs=("risk",),
    )
    issue = ValidationIssue(
        code="wrong_period",
        message="The cited evidence does not match the period stated in the claim.",
        claim_id=claim.claim_id,
    )
    provider = JudgeProvider(resolved_issue_codes=("wrong_period",))

    result = ModelSemanticSupportJudge(provider)(claim, (evidence,), (issue,))

    assert result.status is SemanticSupportStatus.SUPPORTED
    assert result.resolved_issue_codes == ("wrong_period",)
    payload = json.loads(provider.calls[-1][1][-1].content)
    assert payload["validation_issues"][0]["code"] == "wrong_period"
