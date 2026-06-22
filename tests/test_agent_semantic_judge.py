from __future__ import annotations

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
)


class JudgeProvider:
    def __init__(
        self,
        *,
        verdict: Literal["supported", "unsupported"] = "supported",
        refusal: bool = False,
    ) -> None:
        self.verdict = verdict
        self.refusal = refusal

    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        assert purpose is ModelPurpose.VALIDATE
        assert output_type is SemanticSupportJudgment
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
