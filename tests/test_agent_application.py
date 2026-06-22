from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from company_lens.agent import application
from company_lens.agent.semantic_judge import ModelSemanticSupportJudge
from company_lens.config import Settings


def test_semantic_judge_is_disabled_by_default() -> None:
    assert Settings(_env_file=None).semantic_judge_enabled is False


def test_production_agent_assembly_uses_openai_embedder_and_configured_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        OPENAI_API_KEY="test-key",
        agent_retrieval_index_name="production",
        agent_retrieval_index_version="openai-index.v2",
        semantic_judge_enabled=True,
        _env_file=None,
    )
    model = object()
    embedder = object()
    tools = object()
    checkpointer = object()
    repository = object()
    yielded_agent = object()
    embedding_call: dict[str, Any] = {}
    agent_call: dict[str, Any] = {}

    monkeypatch.setattr(application, "_require_research_session_schema", lambda _: None)
    monkeypatch.setattr(application, "build_openai_model_provider", lambda _: model)

    def fake_build_embedder(provider: str, **kwargs: Any) -> object:
        embedding_call.update({"provider": provider, **kwargs})
        return embedder

    monkeypatch.setattr(application, "build_embedder", fake_build_embedder)
    monkeypatch.setattr(application, "build_session_factory", lambda _: object())
    monkeypatch.setattr(application, "SqlResearchTools", lambda **_: tools)
    monkeypatch.setattr(application, "ResearchSessionRepository", lambda _: repository)

    @contextmanager
    def fake_checkpointer(_: str) -> Any:
        yield checkpointer

    monkeypatch.setattr(application, "postgres_checkpointer", fake_checkpointer)

    def fake_agent(**kwargs: Any) -> object:
        agent_call.update(kwargs)
        return yielded_agent

    monkeypatch.setattr(application, "PersistentResearchAgent", fake_agent)

    with application.open_persistent_research_agent(settings) as agent:
        assert agent is yielded_agent

    runtime = agent_call["runtime"]
    assert runtime.model_provider is model
    assert runtime.tools is tools
    assert runtime.retrieval_index_name == "production"
    assert runtime.retrieval_index_version == "openai-index.v2"
    assert isinstance(runtime.semantic_support_judge, ModelSemanticSupportJudge)
    assert embedding_call["provider"] == "openai"
    assert embedding_call["openai_api_key"] == "test-key"
    assert agent_call["checkpointer"] is checkpointer
    assert agent_call["session_repository"] is repository


def test_setup_checks_application_schema_before_checkpoint_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None)
    calls: list[str] = []
    monkeypatch.setattr(
        application,
        "_require_research_session_schema",
        lambda database_url: calls.append(f"schema:{database_url}"),
    )

    @contextmanager
    def fake_checkpointer(database_url: str, *, setup: bool = False) -> Any:
        calls.append(f"checkpointer:{database_url}:{setup}")
        yield object()

    monkeypatch.setattr(application, "postgres_checkpointer", fake_checkpointer)

    application.setup_research_persistence(settings)

    assert calls == [
        f"schema:{settings.database_url}",
        f"checkpointer:{settings.database_url}:True",
    ]


def test_missing_application_schema_has_safe_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    class FakeInspector:
        def has_table(self, name: str) -> bool:
            assert name == "research_sessions"
            return False

    engine = FakeEngine()
    monkeypatch.setattr(application, "create_engine", lambda *_, **__: engine)
    monkeypatch.setattr(application, "inspect", lambda _: FakeInspector())

    with pytest.raises(application.ResearchApplicationConfigurationError) as captured:
        application._require_research_session_schema("postgresql://secret@database")

    assert str(captured.value) == (
        "Research session schema is missing; run `alembic upgrade head` first."
    )
    assert engine.disposed is True
