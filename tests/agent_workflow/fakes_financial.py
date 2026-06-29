from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .shared import *  # noqa: F403
from .builders import _financial_observation
from .fakes_tools import FakeResearchTools

# ruff: noqa: F405

class MixedPeriodFinancialTools(FakeResearchTools):
    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        annual_2023 = _financial_observation(date(2023, 12, 31), Decimal("100"))
        comparative_2023 = annual_2023.model_copy(
            update={
                "id": uuid.uuid4(),
                "fiscal_year": 2024,
                "filed_date": date(2025, 2, 20),
                "accession_number": "2024-comparative",
            }
        )
        return FinancialFactQueryResult(
            query=request,
            observations=(
                _financial_observation(date(2022, 12, 31), Decimal("80")),
                _financial_observation(date(2023, 3, 31), Decimal("20")).model_copy(
                    update={"period_type": "quarter", "fiscal_period": "Q1"}
                ),
                annual_2023,
                comparative_2023,
                _financial_observation(date(2024, 12, 31), Decimal("125")),
            ),
            available_units=("USD",),
        )


class AnnualSeriesFinancialTools(FakeResearchTools):
    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        annual = tuple(
            _financial_observation(date(year, 12, 31), value).model_copy(
                update={"id": ANNUAL_FACT_IDS[year]}
            )
            for year, value in zip(
                range(2022, 2026),
                (Decimal("64"), Decimal("80"), Decimal("100"), Decimal("125")),
                strict=True,
            )
        )
        comparative_2023 = annual[1].model_copy(
            update={
                "id": uuid.uuid4(),
                "filed_date": date(2025, 2, 20),
                "accession_number": "2023-comparative",
            }
        )
        return FinancialFactQueryResult(
            query=request,
            observations=(*annual, comparative_2023),
            available_units=("USD",),
        )


class QuarterlyMissingAnnualFallbackTools(FakeResearchTools):
    def __init__(self, *, annual_observations: bool = True) -> None:
        super().__init__()
        self.annual_observations = annual_observations
        self.financial_requests: list[FinancialFactQuery] = []

    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        self.financial_requests.append(request)
        if request.period_types == ("quarter",):
            return FinancialFactQueryResult(
                query=request,
                observations=(),
                available_units=(),
                warnings=("no_matching_financial_facts",),
            )
        observations = (
            tuple(
                _financial_observation(date(year, 12, 31), value).model_copy(
                    update={"id": ANNUAL_FACT_IDS[year]}
                )
                for year, value in zip(
                    range(2022, 2026),
                    (Decimal("64"), Decimal("80"), Decimal("100"), Decimal("125")),
                    strict=True,
                )
            )
            if self.annual_observations
            else ()
        )
        return FinancialFactQueryResult(
            query=request,
            observations=observations,
            available_units=("USD",) if observations else (),
            warnings=() if observations else ("no_matching_financial_facts",),
        )


class QuarterlyMissingDuplicatedAnnualFallbackTools(QuarterlyMissingAnnualFallbackTools):
    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        if request.period_types == ("quarter",):
            return super().query_financial_facts(request)
        self.calls["financial"] += 1
        self.financial_requests.append(request)
        rows = (
            (2022, Decimal("64"), "FY", date(2023, 2, 1)),
            (2023, Decimal("80"), "FY", date(2024, 2, 1)),
            (2023, Decimal("80"), None, date(2025, 7, 1)),
            (2024, Decimal("100"), "FY", date(2025, 2, 1)),
            (2024, Decimal("100"), None, date(2026, 7, 1)),
            (2025, Decimal("125"), "FY", date(2026, 2, 1)),
        )
        observations = tuple(
            _financial_observation(date(year, 12, 31), value).model_copy(
                update={
                    "id": uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"duplicated-annual-{year}-{fiscal_period}-{filed_date.isoformat()}",
                    ),
                    "company_name": "PEPSICO INC",
                    "ticker": "PEP",
                    "metric": request.metrics[0],
                    "fiscal_period": fiscal_period,
                    "filed_date": filed_date,
                    "accession_number": filed_date.isoformat(),
                    "source_url": f"https://sec.example/pep/{filed_date.isoformat()}",
                }
            )
            for year, value, fiscal_period, filed_date in rows
        )
        return FinancialFactQueryResult(
            query=request,
            observations=observations,
            available_units=("USD",),
        )


class PeerAnnualFinancialTools(FakeResearchTools):
    def resolve_entities(self, query: str) -> ResolvedQuery:
        self.calls["resolve"] += 1
        return ResolvedQuery(
            query=query,
            company_ids=(COMPANY_ID, NETFLIX_ID),
            metrics=("revenue",),
        )

    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        company_id = request.company_ids[0]
        if company_id == NETFLIX_ID:
            company_name = "Netflix"
            ticker = "NFLX"
            values = (Decimal("100"), Decimal("110"), Decimal("132"), Decimal("165"))
        else:
            company_name = "Cloudflare"
            ticker = "NET"
            values = (Decimal("64"), Decimal("80"), Decimal("100"), Decimal("125"))
        return FinancialFactQueryResult(
            query=request,
            observations=tuple(
                _financial_observation(date(year, 12, 31), value).model_copy(
                    update={
                        "id": uuid.uuid5(uuid.NAMESPACE_DNS, f"{company_id}-{year}"),
                        "company_id": company_id,
                        "company_name": company_name,
                        "ticker": ticker,
                    }
                )
                for year, value in zip(range(2022, 2026), values, strict=True)
            ),
            available_units=("USD",),
        )

__all__ = ('MixedPeriodFinancialTools', 'AnnualSeriesFinancialTools', 'QuarterlyMissingAnnualFallbackTools', 'QuarterlyMissingDuplicatedAnnualFallbackTools', 'PeerAnnualFinancialTools')  # noqa: E501
