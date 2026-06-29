from __future__ import annotations
# ruff: noqa: F401, I001

import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Literal, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Overwrite, Send
from pydantic import BaseModel

from company_lens.agent.model import (
    ModelMessage,
    ModelProviderError,
    ModelPurpose,
    ResearchModelProvider,
)
from company_lens.agent.schemas import (
    AgentCapability,
    AgentError,
    AgentErrorCategory,
    AgentErrorSeverity,
    AgentRunStatus,
    AgentState,
    BranchOutcome,
    BranchStatus,
    CachedSourceResult,
    CalculationBranch,
    CalculationBranchResult,
    CalculationOperation,
    ChartBranch,
    CitationReference,
    CompanyMentionCandidate,
    CompanyMentionExtraction,
    CompanyTarget,
    CompanyTargetSource,
    DocumentRetrievalBranch,
    EvidenceEnvelope,
    EvidenceKind,
    ExecutionBranch,
    ExecutionPlan,
    ExecutionPolicy,
    FinancialBranchResult,
    FinancialDataReadiness,
    FinancialDataReadinessStatus,
    FinancialFactsBranch,
    MacroBranchResult,
    MacroSeriesBranch,
    ModelExecutionBranch,
    ModelExecutionPlan,
    NodeAttempt,
    QuestionAnalysis,
    ResearchFrame,
    ResearchRoute,
    RetrievalBranchResult,
    SessionArtifactContext,
    SessionMemory,
    SessionMessage,
    TrajectoryEvent,
    TrajectoryStatus,
)
from company_lens.agent.tools import ResearchToolError, ResearchTools
from company_lens.analytics.calculations import (
    absolute_change,
    compound_annual_growth_rate,
    correlation,
    margin,
    normalised_index,
    percentage_change,
    quarter_over_quarter_growth,
    rolling_average,
    year_over_year_growth_series,
)
from company_lens.analytics.charts import generate_chart_specification
from company_lens.analytics.schemas import (
    CalculationResult,
    ChartPoint,
    ChartSeries,
    ChartSpecification,
    NumericObservation,
    ValidatedChartDataset,
)
from company_lens.evidence.claims import extract_claims
from company_lens.evidence.registry import EvidenceRegistry, SourceChecker
from company_lens.evidence.schemas import (
    ClaimRecord,
    EvidenceMetadata,
    SemanticSupportStatus,
    ValidationIssue,
)
from company_lens.evidence.validation import AnswerValidator, SemanticSupportJudge
from company_lens.financials.schemas import (
    FinancialFactObservation,
    FinancialFactQuery,
    FinancialFactQueryResult,
)
from company_lens.macro.schemas import FredSeriesResult
from company_lens.observability.context import bind_context
from company_lens.observability.telemetry import (
    observe_operation,
    record_cache_access,
    record_retrieval,
    record_validation,
)
from company_lens.retrieval.adaptive_schemas import (
    EntityCandidate,
    EntityResolution,
    ResolvedQuery,
)
from company_lens.retrieval.embeddings import DEFAULT_OPENAI_INDEX_VERSION
from company_lens.security import prompt_injection_flags, sanitize_untrusted_text

SOURCE_KINDS = {"retrieve_documents", "query_financial_facts", "query_macro_series"}
DEFAULT_CHART_QUARTERS = 8
DEFAULT_CHART_QUARTERLY_FACT_LIMIT = 24
DEFAULT_CHART_MACRO_MONTH_LIMIT = 48
MIN_LINE_CHART_POINTS = 3
DEFAULT_CHART_WINDOW_REASON = "default_chart_window_latest_8_quarters"
DETERMINISTIC_PLAN_REASON_CODES = frozenset(
    {
        "deterministic_follow_up_replay_plan",
        "deterministic_multi_company_growth_chart_plan",
        "deterministic_recent_artifact_period_plan",
    }
)
ANNUAL_FINANCIAL_FALLBACK_OPERATIONS = frozenset(
    {
        "year_over_year_growth",
        "cagr",
        "absolute_change",
        "percentage_change",
    }
)
UNIT_NUMBER_RE = re.compile(
    r"(?<![\w.:-])(?P<value>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(?P<unit>USD|percent|%)(?![\w:-])",
    re.IGNORECASE,
)
ChartKind = Literal["line", "bar", "area", "scatter"]
