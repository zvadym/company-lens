from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .shared import *  # noqa: F403
from .builders import _model_execution_plan

# ruff: noqa: F405

class FakeModelProvider:
    def __init__(
        self,
        *,
        analysis: QuestionAnalysis,
        plan: ExecutionPlan,
        company_extraction: CompanyMentionExtraction | None = None,
        texts: Sequence[str] = (),
    ) -> None:
        self.analysis = analysis
        self.plan = plan
        self.company_extraction = company_extraction or CompanyMentionExtraction()
        self.texts = list(texts)
        self.purposes: list[ModelPurpose] = []
        self.model_calls: list[tuple[ModelPurpose, tuple[ModelMessage, ...]]] = []

    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        self.purposes.append(purpose)
        self.model_calls.append((purpose, tuple(messages)))
        if output_type is QuestionAnalysis:
            output: BaseModel = self.analysis
        elif output_type is CompanyMentionExtraction:
            output = self.company_extraction
        elif output_type is ModelExecutionPlan:
            output = _model_execution_plan(self.plan)
        else:
            raise AssertionError(f"Unexpected structured output type: {output_type}")
        return StructuredModelResult[OutputT](
            model="fake-planning",
            response_id=f"response-{purpose}",
            output=cast(OutputT, output),
        )

    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult:
        self.purposes.append(purpose)
        self.model_calls.append((purpose, tuple(messages)))
        return TextModelResult(
            model="fake-answer",
            response_id=f"response-{purpose}-{len(self.purposes)}",
            text=self.texts.pop(0),
        )


class RawPlanModelProvider(FakeModelProvider):
    def __init__(
        self,
        *,
        analysis: QuestionAnalysis,
        raw_plan: ModelExecutionPlan,
        texts: Sequence[str] = (),
    ) -> None:
        super().__init__(analysis=analysis, plan=ExecutionPlan(route=raw_plan.route), texts=texts)
        self.raw_plan = raw_plan

    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        if output_type is not ModelExecutionPlan:
            return super().generate_structured(messages, output_type, purpose=purpose)
        self.purposes.append(purpose)
        self.model_calls.append((purpose, tuple(messages)))
        return StructuredModelResult[OutputT](
            model="fake-planning",
            response_id=f"response-{purpose}",
            output=cast(OutputT, self.raw_plan),
        )


class RepairTimeoutModelProvider(FakeModelProvider):
    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult:
        if purpose is ModelPurpose.REPAIR:
            self.purposes.append(purpose)
            raise ModelProviderError(
                AgentError(
                    category=AgentErrorCategory.PROVIDER_TIMEOUT,
                    severity=AgentErrorSeverity.RECOVERABLE,
                    code="openai_timeout",
                    message="OpenAI request timed out.",
                )
            )
        return super().generate_text(messages, purpose=purpose)


class AnswerTimeoutModelProvider(FakeModelProvider):
    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult:
        if purpose is ModelPurpose.ANSWER:
            self.purposes.append(purpose)
            self.model_calls.append((purpose, tuple(messages)))
            raise ModelProviderError(
                AgentError(
                    category=AgentErrorCategory.PROVIDER_TIMEOUT,
                    severity=AgentErrorSeverity.RECOVERABLE,
                    code="openai_timeout",
                    message="OpenAI request timed out.",
                )
            )
        return super().generate_text(messages, purpose=purpose)


class ParseFailureModelProvider(FakeModelProvider):
    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        if purpose is ModelPurpose.PARSE:
            self.purposes.append(purpose)
            self.model_calls.append((purpose, tuple(messages)))
            raise ModelProviderError(
                AgentError(
                    category=AgentErrorCategory.INTERNAL,
                    severity=AgentErrorSeverity.TERMINAL,
                    code="openai_unexpected",
                    message="Unexpected OpenAI provider failure.",
                )
            )
        return super().generate_structured(messages, output_type, purpose=purpose)


class PlanFailureModelProvider(FakeModelProvider):
    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        if purpose is ModelPurpose.PLAN:
            self.purposes.append(purpose)
            self.model_calls.append((purpose, tuple(messages)))
            raise ModelProviderError(
                AgentError(
                    category=AgentErrorCategory.INTERNAL,
                    severity=AgentErrorSeverity.TERMINAL,
                    code="openai_unexpected",
                    message="Unexpected OpenAI provider failure.",
                )
            )
        return super().generate_structured(messages, output_type, purpose=purpose)

__all__ = ('FakeModelProvider', 'RawPlanModelProvider', 'RepairTimeoutModelProvider', 'AnswerTimeoutModelProvider', 'ParseFailureModelProvider', 'PlanFailureModelProvider')  # noqa: E501
