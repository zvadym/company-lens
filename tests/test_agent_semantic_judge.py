from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from pydantic import BaseModel

from company_lens.agent import (
    ModelMessage,
    ModelPurpose,
    ModelSemanticSupportJudge,
    SemanticSupportJudgment,
    StructuredModelResult,
    TextModelResult,
)
from company_lens.evidence import ClaimRecord, EvidenceEnvelope, EvidenceKind


class JudgeProvider:
    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        assert purpose is ModelPurpose.VALIDATE
        assert output_type is SemanticSupportJudgment
        judgment = SemanticSupportJudgment(supported=True, reason_code="direct_support")
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

    assert ModelSemanticSupportJudge(JudgeProvider())(claim, (evidence,)) is True
