from __future__ import annotations

from company_lens.analytics.schemas import ChartSpecification, ValidatedChartDataset

SUPPORTED_CHART_TYPES = {"line", "bar", "area", "scatter"}


def generate_chart_specification(
    dataset: ValidatedChartDataset,
    *,
    chart_type: str,
    title: str,
    x_label: str = "Date",
) -> ChartSpecification:
    if chart_type not in SUPPORTED_CHART_TYPES:
        raise ValueError(f"Unsupported chart type: {chart_type}")
    if not title.strip() or not x_label.strip():
        raise ValueError("Chart title and axis label must be non-empty.")
    sources = tuple(
        dict.fromkeys(source for point in dataset.points for source in point.source_urls)
    )
    return ChartSpecification(
        chart_type=chart_type,
        title=title,
        x_label=x_label,
        series=dataset.series,
        data=dataset.points,
        sources=sources,
    )
