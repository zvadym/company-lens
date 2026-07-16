from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .shared import *  # noqa: F403
from .builders import _model_execution_plan
from company_lens.agent.calculation_intents import (
    BranchOperationDecision,
    ModelCalculationIntent,
    OperationReconciliation,
)

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
        if output_type is ModelQuestionAnalysis:
            output: BaseModel = _model_question_analysis(self.analysis, self.plan)
        elif output_type is CompanyMentionExtraction:
            output = self.company_extraction
        elif output_type is ModelExecutionPlan:
            output = _model_execution_plan(self.plan)
        elif output_type is OperationReconciliation:
            output = _operation_reconciliation(messages)
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
        if output_type is ModelQuestionAnalysis:
            self.purposes.append(purpose)
            self.model_calls.append((purpose, tuple(messages)))
            values = self.analysis.model_dump()
            if not self.analysis.calculation_intents:
                values["calculation_intents"] = tuple(
                    intent.model_dump()
                    for intent in _model_calculation_intents_from_model_plan(self.raw_plan)
                )
            return StructuredModelResult[OutputT](
                model="fake-planning",
                response_id=f"response-{purpose}",
                output=cast(OutputT, ModelQuestionAnalysis.model_validate(values)),
            )
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


def _model_question_analysis(
    analysis: QuestionAnalysis,
    plan: ExecutionPlan,
) -> ModelQuestionAnalysis:
    values = analysis.model_dump()
    if not analysis.calculation_intents:
        values["calculation_intents"] = tuple(
            intent.model_dump() for intent in _model_calculation_intents(plan)
        )
    return ModelQuestionAnalysis.model_validate(values)


def _model_calculation_intents(plan: ExecutionPlan) -> tuple[ModelCalculationIntent, ...]:
    by_id = {branch.branch_id: branch for branch in plan.branches}
    intents: list[ModelCalculationIntent] = []
    seen: set[tuple[object, ...]] = set()
    for branch in plan.branches:
        if not isinstance(branch, CalculationBranch):
            continue
        metrics: list[str] = []
        for reference in branch.input_refs:
            source = by_id.get(reference)
            if isinstance(source, FinancialFactsBranch):
                metrics.extend(source.request.metrics)
            elif isinstance(source, MacroSeriesBranch):
                metrics.extend(source.request.series_ids)
        intent = ModelCalculationIntent(
            operation=branch.operation,
            metrics=tuple(metrics),
            window=branch.window if branch.operation == "rolling_average" else None,
            years=float(branch.years) if branch.operation == "cagr" else None,
            base=float(branch.base) if branch.operation == "normalised_index" else None,
        )
        signature = (
            intent.operation,
            intent.metrics,
            intent.window,
            intent.years,
            intent.base,
        )
        if signature in seen:
            continue
        seen.add(signature)
        intents.append(intent)
    return tuple(intents)


def _model_calculation_intents_from_model_plan(
    plan: ModelExecutionPlan,
) -> tuple[ModelCalculationIntent, ...]:
    by_id = {branch.branch_id: branch for branch in plan.branches}
    intents: list[ModelCalculationIntent] = []
    for branch in plan.branches:
        if branch.kind != "calculate_metrics" or branch.operation is None:
            continue
        metrics: list[str] = []
        for reference in branch.input_refs:
            source = by_id.get(reference)
            if source is None:
                continue
            if source.financial_request is not None:
                metrics.extend(source.financial_request.metrics)
            elif source.macro_request is not None:
                metrics.extend(source.macro_request.series_ids)
        intents.append(
            ModelCalculationIntent(
                operation=branch.operation,
                metrics=tuple(metrics),
                window=branch.window if branch.operation == "rolling_average" else None,
                years=branch.years if branch.operation == "cagr" else None,
                base=branch.base if branch.operation == "normalised_index" else None,
            )
        )
    return tuple(intents)


def _operation_reconciliation(
    messages: Sequence[ModelMessage],
) -> OperationReconciliation:
    context = json.loads(messages[-1].content)
    intents = context["effective_intents"]
    decisions = []
    for branch in context["calculation_branches"]:
        matching = [
            intent
            for intent in intents
            if not intent["metrics"] or intent["metrics"] == branch["metrics"]
        ]
        intent = matching[0] if matching else intents[0]
        decisions.append(
            BranchOperationDecision(
                branch_id=branch["branch_id"],
                operation=intent["operation"],
                window=intent["window"],
                years=intent["years"],
                base=intent["base"],
            )
        )
    return OperationReconciliation(branch_operations=tuple(decisions))


__all__ = (
    "FakeModelProvider",
    "RawPlanModelProvider",
    "RepairTimeoutModelProvider",
    "AnswerTimeoutModelProvider",
    "ParseFailureModelProvider",
    "PlanFailureModelProvider",
)  # noqa: E501
