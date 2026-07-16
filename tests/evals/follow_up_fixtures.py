from __future__ import annotations

from typing import Any


def follow_up_results() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset_name": "company-lens-follow-up-golden",
        "dataset_version": 1,
        "results": [
            {
                "case_id": "followup_safe_inheritance_chart_001",
                "companies": [
                    {
                        "mention": "Cloudflare",
                        "status": "resolved",
                        "ticker": "NET",
                        "source": "follow_up_context",
                    }
                ],
                "metrics": ["revenue"],
                "operation": "quarter_over_quarter_growth",
                "route": "calculation",
                "tools": [
                    "query_financial_facts",
                    "calculate_metrics",
                    "generate_chart_spec",
                ],
            },
            {
                "case_id": "followup_replace_company_preserve_task_001",
                "companies": [
                    {
                        "mention": "Datadog",
                        "status": "resolved",
                        "ticker": "DDOG",
                        "source": "current_question",
                    }
                ],
                "metrics": ["revenue"],
                "operation": "quarter_over_quarter_growth",
                "route": "calculation",
                "tools": ["query_financial_facts", "calculate_metrics"],
            },
            {
                "case_id": "followup_add_company_to_comparison_001",
                "companies": [
                    {
                        "mention": "Cloudflare",
                        "status": "resolved",
                        "ticker": "NET",
                        "source": "follow_up_context",
                    },
                    {
                        "mention": "Datadog",
                        "status": "resolved",
                        "ticker": "DDOG",
                        "source": "follow_up_context",
                    },
                    {
                        "mention": "MongoDB",
                        "status": "resolved",
                        "ticker": "MDB",
                        "source": "current_question",
                    },
                ],
                "metrics": ["revenue"],
                "operation": "quarter_over_quarter_growth",
                "route": "calculation",
                "tools": ["query_financial_facts", "calculate_metrics"],
            },
            {
                "case_id": "followup_unresolved_company_no_previous_reuse_001",
                "companies": [
                    {
                        "mention": "Globex",
                        "status": "unresolved",
                        "source": "current_question",
                    }
                ],
                "metrics": ["revenue"],
                "operation": "year_over_year_growth",
                "route": "unsupported",
            },
        ],
    }


__all__ = ("follow_up_results",)
