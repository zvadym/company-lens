from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import cast

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from company_lens.db.models import Company, CompanyTicker, FinancialFact
from company_lens.financials.schemas import (
    FinancialFactObservation,
    FinancialFactQuery,
    FinancialFactQueryResult,
    PeriodType,
)


class FinancialFactQueryService:
    def __init__(self, *, session: Session) -> None:
        self._session = session

    def query(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        statement = (
            select(FinancialFact, Company)
            .join(Company, Company.id == FinancialFact.company_id)
            .where(FinancialFact.canonical_metric.in_(request.metrics))
        )
        statement = self._apply_filters(statement, request)
        statement = statement.order_by(
            Company.display_name,
            FinancialFact.canonical_metric,
            FinancialFact.period_end.desc(),
            FinancialFact.filed_date.desc(),
            FinancialFact.accession_number.desc(),
            FinancialFact.id.desc(),
        ).limit(request.limit)
        rows = sorted(
            self._session.execute(statement).all(),
            key=lambda row: (
                row[1].display_name,
                row[0].canonical_metric,
                row[0].period_end,
                row[0].filed_date or date.min,
                row[0].accession_number or "",
                str(row[0].id),
            ),
        )

        tickers = self._ticker_map({fact.company_id for fact, _ in rows})
        conflict_ids = self._conflict_ids([fact for fact, _ in rows])
        observations = tuple(
            FinancialFactObservation(
                id=fact.id,
                company_id=fact.company_id,
                company_name=company.display_name,
                ticker=tickers.get(fact.company_id),
                metric=fact.canonical_metric,
                value=fact.value,
                unit=fact.unit,
                period_start=fact.period_start,
                period_end=fact.period_end,
                period_type=cast(PeriodType, fact.period_type),
                fiscal_year=fact.fiscal_year,
                fiscal_period=fact.fiscal_period,
                form=fact.form,
                filed_date=fact.filed_date,
                accession_number=fact.accession_number,
                taxonomy=fact.taxonomy,
                concept=fact.concept,
                frame=fact.frame,
                is_amendment=fact.is_amendment,
                has_conflict=fact.id in conflict_ids,
                mapping_version=fact.metric_mapping_version,
                source_url=fact.source_url,
            )
            for fact, company in rows
        )
        warnings: list[str] = []
        if not observations:
            warnings.append("no_matching_financial_facts")
        if conflict_ids:
            warnings.append("conflicting_or_restated_values_present")
        return FinancialFactQueryResult(
            query=request,
            observations=observations,
            available_units=tuple(sorted({item.unit for item in observations})),
            warnings=tuple(warnings),
        )

    def _apply_filters(
        self,
        statement: Select[tuple[FinancialFact, Company]],
        request: FinancialFactQuery,
    ) -> Select[tuple[FinancialFact, Company]]:
        if request.company_ids:
            statement = statement.where(FinancialFact.company_id.in_(request.company_ids))
        if request.tickers:
            ticker_company_ids = select(CompanyTicker.company_id).where(
                CompanyTicker.symbol.in_(ticker.upper() for ticker in request.tickers),
                CompanyTicker.valid_to.is_(None),
            )
            statement = statement.where(FinancialFact.company_id.in_(ticker_company_ids))
        if request.period_start:
            statement = statement.where(FinancialFact.period_end >= request.period_start)
        if request.period_end:
            statement = statement.where(FinancialFact.period_end <= request.period_end)
        if request.fiscal_years:
            statement = statement.where(FinancialFact.fiscal_year.in_(request.fiscal_years))
        if request.fiscal_periods:
            statement = statement.where(FinancialFact.fiscal_period.in_(request.fiscal_periods))
        if request.period_types:
            statement = statement.where(FinancialFact.period_type.in_(request.period_types))
        if request.units:
            statement = statement.where(FinancialFact.unit.in_(request.units))
        if not request.include_amendments:
            statement = statement.where(FinancialFact.is_amendment.is_(False))
        return statement

    def _ticker_map(self, company_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not company_ids:
            return {}
        rows = self._session.execute(
            select(CompanyTicker.company_id, CompanyTicker.symbol)
            .where(
                CompanyTicker.company_id.in_(company_ids),
                CompanyTicker.is_primary.is_(True),
                CompanyTicker.valid_to.is_(None),
            )
            .order_by(CompanyTicker.company_id, CompanyTicker.symbol)
        ).all()
        result: dict[uuid.UUID, str] = {}
        for company_id, symbol in rows:
            result.setdefault(company_id, symbol)
        return result

    @staticmethod
    def _conflict_ids(facts: list[FinancialFact]) -> set[uuid.UUID]:
        groups: defaultdict[tuple[object, ...], list[FinancialFact]] = defaultdict(list)
        for fact in facts:
            groups[
                (
                    fact.company_id,
                    fact.canonical_metric,
                    fact.period_start,
                    fact.period_end,
                    fact.period_type,
                    fact.unit,
                    fact.fiscal_period,
                )
            ].append(fact)
        conflicts: set[uuid.UUID] = set()
        for group in groups.values():
            values: set[Decimal] = {fact.value for fact in group}
            if len(values) > 1:
                conflicts.update(fact.id for fact in group)
        return conflicts
