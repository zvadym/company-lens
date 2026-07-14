from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from company_lens.agent.model import ModelMessage, ModelPurpose
from company_lens.agent.openai_provider import OpenAIResearchModelProvider
from company_lens.agent.schemas import AgentCapability, QuestionAnalysis, ResearchRoute
from company_lens.agent.workflow_model_calls import _generate_structured_with_retries


class InvalidThenValidResponses:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, **_kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        if self.calls == 1:
            QuestionAnalysis.model_validate(
                {
                    "normalized_question": "Datadog risk factors",
                    "route": "rag_only",
                    "required_capabilities": ["documents"],
                    "reason_codes": ["10k_risks"],
                }
            )
        output = QuestionAnalysis(
            normalized_question="Datadog risk factors",
            route=ResearchRoute.RAG_ONLY,
            required_capabilities=(AgentCapability.DOCUMENTS,),
            reason_codes=("annual_report_risks",),
        )
        return SimpleNamespace(
            id="resp_valid_retry",
            model="planning-model",
            output=(),
            output_parsed=output,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
        )


def test_invalid_structured_output_is_retried_by_the_workflow() -> None:
    responses = InvalidThenValidResponses()
    provider = OpenAIResearchModelProvider(
        api_key="test-key",
        planning_model="planning-model",
        client=SimpleNamespace(responses=responses),
    )

    output, attempts, error = _generate_structured_with_retries(
        provider,
        (
            ModelMessage(role="system", content="Classify the question."),
            ModelMessage(role="user", content="What are Datadog's 10-K risks?"),
        ),
        QuestionAnalysis,
        purpose=ModelPurpose.PARSE,
        max_retries=1,
        node="parse_question",
    )

    assert output is not None
    assert output.reason_codes == ("annual_report_risks",)
    assert attempts == 2
    assert error is None
    assert responses.calls == 2
