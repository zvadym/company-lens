from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from company_lens.agent.schemas import AgentErrorCategory, AgentErrorSeverity
from company_lens.agent.tools import ResearchToolError, SqlResearchTools
from company_lens.retrieval.adaptive_schemas import ResolvedQuery


def test_sql_research_tools_owns_a_distinct_session_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions: list[Session] = []

    class TrackingResolver:
        def __init__(self, *, session: Session) -> None:
            sessions.append(session)

        def resolve(self, query: str) -> ResolvedQuery:
            return ResolvedQuery(query=query)

    monkeypatch.setattr("company_lens.agent.tools.EntityResolver", TrackingResolver)
    factory = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:"))
    tools = SqlResearchTools(session_factory=factory)

    tools.resolve_entities("first")
    tools.resolve_entities("second")

    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]


def test_sql_research_tools_sanitizes_unexpected_service_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenResolver:
        def __init__(self, *, session: Session) -> None:
            pass

        def resolve(self, query: str) -> Any:
            raise RuntimeError("database failed with sk-secret-value")

    monkeypatch.setattr("company_lens.agent.tools.EntityResolver", BrokenResolver)
    factory = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:"))
    tools = SqlResearchTools(session_factory=factory)

    with pytest.raises(ResearchToolError) as captured:
        tools.resolve_entities("query")

    assert captured.value.error.category is AgentErrorCategory.TOOL
    assert captured.value.error.severity is AgentErrorSeverity.RECOVERABLE
    assert "sk-secret-value" not in str(captured.value)
