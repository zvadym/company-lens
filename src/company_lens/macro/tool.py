from __future__ import annotations

from importlib import import_module
from typing import Any

from company_lens.macro.schemas import FredSeriesQuery
from company_lens.macro.service import FredQueryService


def build_langchain_fred_tool(service: FredQueryService) -> Any:
    try:
        structured_tool = import_module("langchain_core.tools").StructuredTool
    except (ImportError, AttributeError) as exc:
        raise RuntimeError("langchain-core is required to build the FRED tool.") from exc

    def query_fred_series(**kwargs: Any) -> dict[str, Any]:
        request = FredSeriesQuery.model_validate(kwargs)
        return service.query(request).model_dump(mode="json")

    return structured_tool.from_function(
        func=query_fred_series,
        name="query_fred_series",
        description=(
            "Query cached FRED macroeconomic observations by series and date range. "
            "Returns values, units, frequency, revisions, metadata, and source URLs."
        ),
        args_schema=FredSeriesQuery,
    )
