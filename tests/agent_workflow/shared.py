from __future__ import annotations
# ruff: noqa: F401, I001

import json
import threading
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import cast

import pytest
from langgraph.runtime import Runtime
from pydantic import BaseModel

from company_lens.agent import (
    AgentCapability,
    AgentError,
    AgentErrorCategory,
    AgentErrorSeverity,
    AgentRunStatus,
    BranchOutcome,
    BranchStatus,
    ExecutionPlan,
    ExecutionPolicy,
    FinancialFactsBranch,
    MacroSeriesBranch,
    ModelMessage,
    ModelPurpose,
    QuestionAnalysis,
    ResearchAgent,
    ResearchAgentRuntime,
    ResearchRoute,
    ResearchToolError,
    StructuredModelResult,
    TextModelResult,
)
from company_lens.agent.model import ModelProviderError
from company_lens.agent.schemas import (
    CalculationBranch,
    CalculationBranchResult,
    ChartBranch,
    CompanyMentionCandidate,
    CompanyMentionExtraction,
    DocumentRetrievalBranch,
    ModelExecutionBranch,
    ModelExecutionPlan,
    ResearchFrame,
    SessionArtifactContext,
    SessionMemory,
)
from company_lens.agent.workflow import (
    _fallback_multi_company_growth_chart_plan,
    _generate_chart_spec,
    _merge_follow_up_if_needed,
    _merge_follow_up_resolution,
    _parse_question,
    _plan_request,
    _prepare_company_data,
    _resolve_entities,
    _updated_session_memory,
    build_research_graph,
    create_initial_agent_state,
)
from company_lens.analytics.schemas import CalculationPoint, CalculationResult
from company_lens.financials.schemas import (
    FinancialFactObservation,
    FinancialFactQuery,
    FinancialFactQueryResult,
)
from company_lens.ingestion.on_demand import CompanyDataPreparationResult
from company_lens.macro.schemas import (
    FredObservation,
    FredSeriesQuery,
    FredSeriesResult,
)
from company_lens.retrieval.adaptive_schemas import (
    AdaptiveRetrievalRequest,
    AdaptiveRetrievalResponse,
    ContextEvidence,
    EntityCandidate,
    EntityResolution,
    ResolvedQuery,
    RetrievalPlan,
    RetrievalTrace,
)
from company_lens.retrieval.resolution import public_company_resolution

COMPANY_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
NETFLIX_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
APPLE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
ZOOM_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
NOKIA_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
MICROSOFT_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
AMAZON_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")
FACT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
ANNUAL_FACT_IDS = {
    year: uuid.uuid5(uuid.NAMESPACE_DNS, f"company-lens-test-revenue-{year}")
    for year in range(2022, 2026)
}

__all__ = tuple(name for name in globals() if not name.startswith("__"))
