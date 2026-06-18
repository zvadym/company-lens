from __future__ import annotations

from importlib import import_module
from typing import Any

from company_lens.financials.schemas import FinancialFactQuery
from company_lens.financials.service import FinancialFactQueryService


def build_langchain_financial_facts_tool(service: FinancialFactQueryService) -> Any:
    """Build a LangChain StructuredTool without coupling the core package to LangChain.

    Applications that enable the agent layer install ``langchain-core`` and call this factory.
    Keeping the import lazy lets ingestion and deterministic analytics run independently.
    """

    try:
        structured_tool = import_module("langchain_core.tools").StructuredTool
    except (ImportError, AttributeError) as exc:
        raise RuntimeError("langchain-core is required to build the financial facts tool.") from exc

    def query_financial_facts(**kwargs: Any) -> dict[str, Any]:
        request = FinancialFactQuery.model_validate(kwargs)
        return service.query(request).model_dump(mode="json")

    return structured_tool.from_function(
        func=query_financial_facts,
        name="query_financial_facts",
        description=(
            "Query canonical SEC financial observations by company, metric, reporting period, "
            "and unit. Returns ordered values with complete SEC provenance."
        ),
        args_schema=FinancialFactQuery,
    )
