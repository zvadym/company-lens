from __future__ import annotations
# ruff: noqa: F401, I001

from importlib import import_module
from types import ModuleType

from company_lens.agent.workflow_core import (
    ResearchAgent,
    ResearchAgentRuntime,
    build_research_graph,
    create_initial_agent_state,
    research_graph_mermaid,
)

_WORKFLOW_MODULE_NAMES = (
    "workflow_core",
    "workflow_lifecycle",
    "workflow_session",
    "workflow_mentions",
    "workflow_mention_resolution",
    "workflow_resolution",
    "workflow_preparation",
    "workflow_frame",
    "workflow_readiness",
    "workflow_plan_prompts",
    "workflow_plan_request",
    "workflow_plan_deterministic",
    "workflow_replay_financial",
    "workflow_followup_intent",
    "workflow_artifact_period",
    "workflow_multi_company",
    "workflow_cache",
    "workflow_financial_sources",
    "workflow_macro_sources",
    "workflow_evaluation",
    "workflow_execution",
    "workflow_answer",
    "workflow_citations",
    "workflow_evidence_context",
    "workflow_deterministic_answer",
    "workflow_fallback_tables",
    "workflow_display",
    "workflow_finalize",
    "workflow_plan_validation",
    "workflow_chart_window",
    "workflow_plan_conversion",
    "workflow_branch_utils",
    "workflow_followup_merge",
    "workflow_recent_context",
    "workflow_branch_evidence",
    "workflow_calculations",
    "workflow_chart_dataset",
    "workflow_chart_points",
    "workflow_state_evidence",
    "workflow_model_calls",
    "workflow_errors",
)

_workflow_modules: tuple[ModuleType, ...] = tuple(
    import_module(f"{__package__}.{module_name}") for module_name in _WORKFLOW_MODULE_NAMES
)
_workflow_exports: dict[str, object] = {}
for _workflow_module in _workflow_modules:
    for _name in getattr(_workflow_module, "__all__", ()):  # pragma: no branch
        _workflow_exports[_name] = getattr(_workflow_module, _name)

# Split modules keep the old monolithic helper call graph; populate each module's
# globals after import so moved private helpers resolve exactly as they did before.
for _workflow_module in _workflow_modules:
    _workflow_module.__dict__.update(_workflow_exports)

globals().update(_workflow_exports)
__all__ = (
    "ResearchAgent",
    "ResearchAgentRuntime",
    "build_research_graph",
    "create_initial_agent_state",
    "research_graph_mermaid",
)
