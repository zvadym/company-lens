from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _chart_references(branch: ChartBranch) -> tuple[str, ...]:
    return tuple(dict.fromkeys(branch.depends_on or (branch.dataset_ref,)))


def _chart_dataset_for_branch(branch: ChartBranch, state: AgentState) -> ValidatedChartDataset:
    references = _chart_references(branch)
    if len(references) == 1:
        return _chart_dataset(references[0], state)
    return _multi_series_chart_dataset(references, state)


def _chart_dataset(reference: str, state: AgentState) -> ValidatedChartDataset:
    observations = _numeric_series_for_chart(reference, state)
    if observations is not None:
        if not observations:
            raise ValueError("Chart source has no observations.")
        units = {item.unit for item in observations}
        if len(units) != 1:
            raise ValueError("Chart source contains incompatible units.")
        key = reference
        return ValidatedChartDataset(
            series=(ChartSeries(key=key, label=observations[0].label, unit=units.pop()),),
            points=tuple(
                ChartPoint(
                    x=item.observed_at,
                    values={key: item.value},
                    source_urls=(item.source_url,),
                )
                for item in observations
                if item.observed_at is not None and item.value is not None
            ),
        )
    calculation = next(
        (item for item in state.get("calculations", ()) if item.branch_id == reference),
        None,
    )
    if calculation is None:
        raise ValueError("Chart dataset reference is missing.")
    if any(point.observed_at is None for point in calculation.result.values):
        raise ValueError("Scalar calculations without dates cannot be charted.")
    return ValidatedChartDataset(
        series=(
            ChartSeries(
                key=reference,
                label=_calculation_series_label(calculation.result),
                unit=calculation.result.unit,
            ),
        ),
        points=tuple(
            ChartPoint(
                x=cast(date, point.observed_at),
                values={reference: point.value},
                source_urls=calculation.result.sources,
            )
            for point in calculation.result.values
        ),
    )


def _multi_series_chart_dataset(
    references: Sequence[str],
    state: AgentState,
) -> ValidatedChartDataset:
    series_data = tuple(_chart_series_points(reference, state) for reference in references)
    if not series_data:
        raise ValueError("Chart requires at least one dataset reference.")
    common_dates = set(series_data[0][1])
    for _, points in series_data[1:]:
        common_dates &= set(points)
    point_limit = _chart_point_limit(state)
    if not common_dates:
        return _aligned_multi_series_chart_dataset(series_data, point_limit=point_limit)
    ordered_dates = tuple(sorted(common_dates))
    if point_limit is not None:
        ordered_dates = ordered_dates[-point_limit:]
    return ValidatedChartDataset(
        series=tuple(series for series, _ in series_data),
        points=tuple(
            ChartPoint(
                x=observed_at,
                values={series.key: points[observed_at][0] for series, points in series_data},
                source_urls=tuple(
                    dict.fromkeys(
                        source_url
                        for _, points in series_data
                        for source_url in points[observed_at][1]
                    )
                ),
            )
            for observed_at in ordered_dates
        ),
    )


def _aligned_multi_series_chart_dataset(
    series_data: Sequence[tuple[ChartSeries, dict[date, tuple[Decimal, tuple[str, ...]]]]],
    *,
    point_limit: int | None = None,
) -> ValidatedChartDataset:
    primary_series, primary_points = series_data[0]
    primary_dates = tuple(sorted(primary_points))
    if point_limit is not None:
        primary_dates = primary_dates[-point_limit:]
    chart_points: list[ChartPoint] = []
    for observed_at in primary_dates:
        values = {primary_series.key: primary_points[observed_at][0]}
        source_urls = list(primary_points[observed_at][1])
        for series, points in series_data[1:]:
            matched_at = _latest_observation_at_or_before(tuple(points), observed_at)
            if matched_at is None:
                break
            values[series.key] = points[matched_at][0]
            source_urls.extend(points[matched_at][1])
        else:
            chart_points.append(
                ChartPoint(
                    x=observed_at,
                    values=values,
                    source_urls=tuple(dict.fromkeys(source_urls)),
                )
            )
    if not chart_points:
        raise ValueError("Chart series do not share alignable observation dates.")
    return ValidatedChartDataset(
        series=tuple(series for series, _ in series_data),
        points=tuple(chart_points),
    )


def _chart_point_limit(state: AgentState) -> int | None:
    plan = state.get("execution_plan")
    if plan is not None and DEFAULT_CHART_WINDOW_REASON in plan.reason_codes:
        return DEFAULT_CHART_QUARTERS
    return None

__all__ = ('_chart_references', '_chart_dataset_for_branch', '_chart_dataset', '_multi_series_chart_dataset', '_aligned_multi_series_chart_dataset', '_chart_point_limit')  # noqa: E501
