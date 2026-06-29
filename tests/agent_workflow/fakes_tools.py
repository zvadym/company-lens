from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .shared import *  # noqa: F403
from .builders import _financial_observation

# ruff: noqa: F405

class FakeResearchTools:
    def __init__(self, *, synchronize_sources: bool = False) -> None:
        self.calls: defaultdict[str, int] = defaultdict(int)
        self.thread_ids: set[int] = set()
        self.retrieval_requests: list[AdaptiveRetrievalRequest] = []
        self.barrier = threading.Barrier(2) if synchronize_sources else None

    def resolve_entities(self, query: str) -> ResolvedQuery:
        self.calls["resolve"] += 1
        return ResolvedQuery(query=query, company_ids=(COMPANY_ID,), metrics=("revenue",))

    def resolve_non_company_entities(self, query: str) -> ResolvedQuery:
        resolved = self.resolve_entities(query)
        has_company_entities = any(
            entity.kind in {"company", "public_company"} for entity in resolved.entities
        )
        return resolved.model_copy(
            update={
                "entities": tuple(
                    entity
                    for entity in resolved.entities
                    if entity.kind not in {"company", "public_company"}
                ),
                "company_ids": () if has_company_entities else resolved.company_ids,
            }
        )

    def resolve_public_company_mentions(
        self,
        candidates: Sequence[CompanyMentionCandidate],
    ) -> tuple[EntityResolution, ...]:
        self.calls["resolve_public_company_mentions"] += 1
        return ()

    def prepare_companies(
        self,
        *,
        tickers: tuple[str, ...],
        company_ids: tuple[str, ...],
        index_name: str,
        index_version: str,
    ) -> CompanyDataPreparationResult:
        self.calls["prepare"] += 1
        return CompanyDataPreparationResult(
            status="skipped",
            requested_tickers=tickers,
            skipped_tickers=tickers,
            prepared_tickers=(),
        )

    def retrieve_documents(self, request: AdaptiveRetrievalRequest) -> AdaptiveRetrievalResponse:
        self.calls["retrieval"] += 1
        self.retrieval_requests.append(request)
        plan = RetrievalPlan(query=request.query, strategy="summary_only")
        return AdaptiveRetrievalResponse(
            query=request.query,
            resolved_query=ResolvedQuery(query=request.query, company_ids=(COMPANY_ID,)),
            plan=plan,
            context=(
                ContextEvidence(
                    kind="document_summary",
                    content="Cloudflare identified competition as a material business risk.",
                    citation_label="document:cloudflare-risk",
                    source_url="https://sec.example/risk",
                    source_id="cloudflare-risk",
                    company_id=COMPANY_ID,
                    company_name="Cloudflare",
                    token_count=10,
                ),
            ),
            trace=RetrievalTrace(
                initial_plan=plan,
                attempts=(),
                final_context_tokens=10,
            ),
        )

    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self._synchronize("financial")
        return FinancialFactQueryResult(
            query=request,
            observations=(
                _financial_observation(date(2024, 12, 31), Decimal("100")),
                _financial_observation(date(2025, 12, 31), Decimal("125")),
            ),
            available_units=("USD",),
        )

    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        self._synchronize("macro")
        return FredSeriesResult(
            query=request,
            series=(),
            observations=(
                FredObservation(
                    series_id="FEDFUNDS",
                    observed_at=date(2025, 12, 1),
                    realtime_start=date(2025, 12, 1),
                    realtime_end=date(2025, 12, 1),
                    value=Decimal("3.5"),
                    raw_value="3.5",
                    is_missing=False,
                    unit="percent",
                    frequency="Monthly",
                    source_url="https://fred.example/FEDFUNDS",
                ),
            ),
        )

    def _synchronize(self, name: str) -> None:
        self.calls[name] += 1
        self.thread_ids.add(threading.get_ident())
        if self.barrier is not None:
            self.barrier.wait(timeout=2)


class AnnualMacroTools(FakeResearchTools):
    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        self.calls["macro"] += 1
        return FredSeriesResult(
            query=request,
            series=(),
            observations=tuple(
                FredObservation(
                    series_id="FEDFUNDS",
                    observed_at=date(year, 12, 31),
                    realtime_start=date(year, 12, 31),
                    realtime_end=date(year, 12, 31),
                    value=value,
                    raw_value=str(value),
                    is_missing=False,
                    unit="percent",
                    frequency="Annual",
                    source_url=f"https://fred.example/FEDFUNDS/{year}",
                )
                for year, value in (
                    (2023, Decimal("5.25")),
                    (2024, Decimal("5.00")),
                    (2025, Decimal("4.50")),
                )
            ),
        )

__all__ = ('FakeResearchTools', 'AnnualMacroTools')
