from __future__ import annotations

PLAN_REQUEST_SYSTEM_PROMPT = (
    "Create a minimal typed execution plan for CompanyLens. Use only resolved company "
    "IDs. Company metrics use query_financial_facts; economic rates and indicators "
    "use query_macro_series. A requested change or growth requires a calculation route "
    "with a source branch and calculate_metrics branch. Source branches must be "
    "independent. Calculations may depend on financial or macro branches. A chart may "
    "depend on one numeric branch, but comparison charts must depend on every plotted "
    "source or calculation branch. The plan route must describe its concrete branches. "
    "Mark a branch optional only when the question can still be answered without it. "
    "For follow-up requests, use recent_artifacts to resolve references like same, "
    "that chart, there, previous, add to it, or a changed period before inventing a "
    "new task shape. Preserve the referenced artifact's companies, metrics, "
    "calculation operations, and chart type unless the user explicitly overrides them. "
    "Do not include explanations beyond short reason codes. "
    "Use English for all structured fields, internal planning labels, reason codes, "
    "and tool-oriented summaries."
)

__all__ = ("PLAN_REQUEST_SYSTEM_PROMPT",)
