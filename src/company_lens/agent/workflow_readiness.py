from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _previous_calculation_window(memory: SessionMemory | None) -> int | None:
    if memory is None or memory.last_execution_plan is None:
        return None
    for branch in reversed(memory.last_execution_plan.branches):
        if isinstance(branch, CalculationBranch) and branch.window is not None:
            return branch.window
    return None


def _probe_financial_readiness_if_needed(
    frame: ResearchFrame,
    tools: ResearchTools,
) -> ResearchFrame:
    if frame.financial_readiness or not _should_probe_financial_readiness(frame):
        return frame
    readiness: list[FinancialDataReadiness] = []
    for company_id in frame.resolved_query.company_ids:
        for metric in frame.resolved_query.metrics:
            result = tools.query_financial_facts(
                FinancialFactQuery(
                    company_ids=(company_id,),
                    metrics=(metric,),
                    fiscal_years=frame.resolved_query.fiscal_years,
                    fiscal_periods=frame.resolved_query.fiscal_periods,
                    limit=_financial_readiness_limit(frame),
                )
            )
            observation_count = len(result.observations)
            readiness.append(
                FinancialDataReadiness(
                    company_id=company_id,
                    metric=metric,
                    status=_financial_readiness_status(frame, observation_count),
                    observation_count=observation_count,
                    warnings=result.warnings,
                )
            )
    return frame.model_copy(update={"financial_readiness": tuple(readiness)})


def _should_probe_financial_readiness(frame: ResearchFrame) -> bool:
    return (
        frame.analysis.is_follow_up
        and AgentCapability.FINANCIAL_FACTS in frame.analysis.required_capabilities
        and bool(frame.resolved_query.company_ids)
        and bool(frame.resolved_query.metrics)
        and not frame.inherited_from_previous
        and any(target.source == "current_question" for target in frame.company_targets)
    )


def _financial_readiness_limit(frame: ResearchFrame) -> int:
    minimum = _minimum_observations_for_operation(frame.follow_up_operation)
    return max(minimum, frame.follow_up_window or minimum)


def _minimum_observations_for_operation(operation: CalculationOperation | None) -> int:
    if operation in {
        "quarter_over_quarter_growth",
        "year_over_year_growth",
        "cagr",
        "absolute_change",
        "percentage_change",
    }:
        return 2
    return 1


def _financial_readiness_status(
    frame: ResearchFrame,
    observation_count: int,
) -> FinancialDataReadinessStatus:
    if observation_count == 0:
        return "missing"
    if observation_count < _minimum_observations_for_operation(frame.follow_up_operation):
        return "partial"
    return "available"


def _missing_required_financial_readiness(
    frame: ResearchFrame,
) -> tuple[FinancialDataReadiness, ...]:
    if not _should_probe_financial_readiness(frame):
        return ()
    return tuple(item for item in frame.financial_readiness if item.status == "missing")


def _financial_readiness_error(
    missing: tuple[FinancialDataReadiness, ...],
) -> AgentError:
    metrics = ",".join(tuple(dict.fromkeys(item.metric for item in missing)))
    return _agent_error(
        "plan_request",
        "financial_data_missing",
        f"Required structured financial facts were unavailable for: {metrics}.",
        category=AgentErrorCategory.TOOL,
        severity=AgentErrorSeverity.TERMINAL,
    )


def _financial_readiness_answer(
    frame: ResearchFrame,
    missing: tuple[FinancialDataReadiness, ...],
) -> str:
    company = _readiness_company_label(frame)
    metrics = ", ".join(tuple(dict.fromkeys(item.metric for item in missing)))
    if _looks_ukrainian(frame.question):
        return (
            f"Не можу виконати цей запит для {company}: після підготовки даних не знайшов "
            f"структурованих фінансових фактів для метрик: {metrics}. "
            "Тому план з розрахунком не запускався, щоб не повертати результат по "
            "попередній компанії."
        )
    return (
        f"I cannot complete this request for {company}: after preparing company data, "
        f"structured financial facts were unavailable for: {metrics}. "
        "The calculation plan was not run so the previous company would not be reused."
    )


def _ambiguous_company_entities(resolved: ResolvedQuery) -> tuple[EntityResolution, ...]:
    return tuple(
        entity
        for entity in resolved.entities
        if entity.kind in {"company", "public_company"} and entity.status == "ambiguous"
    )


def _ambiguous_company_answer(
    frame: ResearchFrame,
    entities: tuple[EntityResolution, ...],
) -> str:
    entity = entities[0]
    mention = entity.mention
    candidates = _ambiguous_company_candidate_lines(entity)
    if _looks_ukrainian(frame.question):
        return (
            f"Уточніть, будь ласка, яку компанію ви маєте на увазі під `{mention}`.\n\n"
            f"Я знайшов кілька SEC matches:\n{candidates}\n\n"
            "Відповідайте ticker або повною юридичною назвою, і я запущу той самий "
            "аналіз для вибраної компанії."
        )
    return (
        f"Please clarify which company you mean by `{mention}`.\n\n"
        f"I found multiple SEC matches:\n{candidates}\n\n"
        "Reply with the ticker or full legal name, and I'll run the same analysis for "
        "that company."
    )


def _ambiguous_company_candidate_lines(entity: EntityResolution) -> str:
    if not entity.candidates:
        return "- Multiple SEC-listed companies"
    return "\n".join(
        f"- {_ambiguous_company_candidate_label(candidate)}" for candidate in entity.candidates
    )


def _ambiguous_company_candidate_label(candidate: EntityCandidate) -> str:
    display = candidate.display_value
    canonical = candidate.canonical_value.strip()
    if canonical and canonical != display and _uuid_or_none(canonical) is None:
        return f"{display} ({canonical})"
    return display


def _missing_company_answer(frame: ResearchFrame) -> str:
    company = _readiness_company_label(frame)
    if _looks_ukrainian(frame.question):
        return (
            f"Не можу виконати цей запит для {company}: зараз підтримуються тільки "
            "публічні компанії, які можна однозначно знайти через SEC/EDGAR filings. "
            "Я не знайшов таку компанію або ticker у доступних джерелах. Розрахунок "
            "не запускався, щоб не повернути результат по попередній компанії. "
            "Спробуйте вказати SEC ticker або повну юридичну назву компанії."
        )
    return (
        f"I cannot complete this request for {company}: CompanyLens currently supports "
        "only public companies that can be resolved through SEC/EDGAR filings. I could "
        "not resolve that company or ticker from the available sources. The calculation "
        "plan was not run so the previous company would not be reused. Try using the SEC "
        "ticker or the company's full legal name."
    )


def _readiness_company_label(frame: ResearchFrame) -> str:
    for target in frame.company_targets:
        if target.display_name:
            return target.display_name
        if target.ticker:
            return target.ticker
        if target.mention:
            return target.mention
    return "the resolved company"


__all__ = (
    "_previous_calculation_window",
    "_probe_financial_readiness_if_needed",
    "_should_probe_financial_readiness",
    "_financial_readiness_limit",
    "_minimum_observations_for_operation",
    "_financial_readiness_status",
    "_missing_required_financial_readiness",
    "_financial_readiness_error",
    "_financial_readiness_answer",
    "_ambiguous_company_entities",
    "_ambiguous_company_answer",
    "_ambiguous_company_candidate_lines",
    "_ambiguous_company_candidate_label",
    "_missing_company_answer",
    "_readiness_company_label",
)  # noqa: E501
