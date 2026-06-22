from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from company_lens.agent.model import (
    ModelMessage,
    ModelProviderError,
    ModelPurpose,
    ResearchModelProvider,
)
from company_lens.evidence.schemas import (
    ClaimRecord,
    EvidenceEnvelope,
    EvidenceKind,
    SemanticSupportResult,
    SemanticSupportStatus,
)

SEMANTIC_JUDGE_PROMPT_VERSION = "semantic-support.v1"


class SemanticSupportJudgment(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: Literal["supported", "unsupported"]
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class ModelSemanticSupportJudge:
    """Optional semantic support check used after deterministic validation passes."""

    def __init__(self, provider: ResearchModelProvider) -> None:
        self._provider = provider

    def __call__(
        self, claim: ClaimRecord, evidence: tuple[EvidenceEnvelope, ...]
    ) -> SemanticSupportResult:
        if not any(item.kind is EvidenceKind.DOCUMENT for item in evidence):
            return SemanticSupportResult(
                status=SemanticSupportStatus.NOT_RUN,
                reason_code="deterministic_validation_sufficient",
                prompt_version=SEMANTIC_JUDGE_PROMPT_VERSION,
            )
        try:
            result = self._provider.generate_structured(
                (
                    ModelMessage(
                        role="system",
                        content=(
                            "Judge whether the supplied evidence directly and completely supports "
                            "the claim. Use verdict=supported only when the evidence entails the "
                            "material assertion. Use verdict=unsupported for contradictions, "
                            "unrelated evidence, material omissions, or causal claims supported "
                            "only by correlation. Do not use outside knowledge. Return only the "
                            "structured judgment."
                        ),
                    ),
                    ModelMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "claim": claim.model_dump(mode="json"),
                                "evidence": [item.model_dump(mode="json") for item in evidence],
                            },
                            sort_keys=True,
                        ),
                    ),
                ),
                SemanticSupportJudgment,
                purpose=ModelPurpose.VALIDATE,
            )
        except ModelProviderError as exc:
            return SemanticSupportResult(
                status=SemanticSupportStatus.UNAVAILABLE,
                reason_code=exc.error.code,
                prompt_version=SEMANTIC_JUDGE_PROMPT_VERSION,
            )
        if result.output is None:
            return SemanticSupportResult(
                status=SemanticSupportStatus.UNAVAILABLE,
                reason_code="semantic_judge_refusal",
                prompt_version=SEMANTIC_JUDGE_PROMPT_VERSION,
                model=result.model,
            )
        return SemanticSupportResult(
            status=(
                SemanticSupportStatus.SUPPORTED
                if result.output.verdict == "supported"
                else SemanticSupportStatus.UNSUPPORTED
            ),
            reason_code=result.output.reason_code,
            prompt_version=SEMANTIC_JUDGE_PROMPT_VERSION,
            model=result.model,
        )
