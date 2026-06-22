from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from company_lens.agent.model import (
    ModelMessage,
    ModelProviderError,
    ModelPurpose,
    ResearchModelProvider,
)
from company_lens.evidence.schemas import ClaimRecord, EvidenceEnvelope


class SemanticSupportJudgment(BaseModel):
    model_config = ConfigDict(frozen=True)

    supported: bool
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class ModelSemanticSupportJudge:
    """Optional semantic support check used after deterministic validation passes."""

    def __init__(self, provider: ResearchModelProvider) -> None:
        self._provider = provider

    def __call__(self, claim: ClaimRecord, evidence: tuple[EvidenceEnvelope, ...]) -> bool:
        try:
            result = self._provider.generate_structured(
                (
                    ModelMessage(
                        role="system",
                        content=(
                            "Decide whether the supplied evidence directly supports the claim. "
                            "Do not use outside knowledge. Numerical, company, period, and unit "
                            "details must agree. Return only the structured judgment."
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
        except ModelProviderError:
            return False
        return result.output.supported if result.output is not None else False
