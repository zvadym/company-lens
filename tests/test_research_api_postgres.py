from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import create_engine

from company_lens.db.models import (
    RateLimitBucket,
    ResearchEvent,
    ResearchFeedback,
    ResearchRun,
)
from company_lens.db.session import build_session_factory
from company_lens.research.repository import RateLimitExceededError, ResearchRunRepository
from company_lens.research.schemas import StartResearchRequest

pytestmark = pytest.mark.skipif(
    not os.getenv("COMPANY_LENS_TEST_DATABASE_URL"),
    reason="COMPANY_LENS_TEST_DATABASE_URL is not set.",
)

TABLES = (
    ResearchRun.__table__,
    ResearchEvent.__table__,
    ResearchFeedback.__table__,
    RateLimitBucket.__table__,
)


def test_postgres_claim_reconnect_and_rate_limit_are_durable() -> None:
    database_url = os.environ["COMPANY_LENS_TEST_DATABASE_URL"]
    engine = create_engine(database_url)
    ResearchRun.metadata.create_all(engine, tables=TABLES)
    try:
        repository = ResearchRunRepository(build_session_factory(database_url))
        run = repository.enqueue(
            StartResearchRequest(question="Concurrent claim"),
            session_id=f"postgres-api-{uuid.uuid4()}",
            timeout=timedelta(minutes=5),
        )

        def claim(worker: str):
            return repository.claim(worker, lease=timedelta(seconds=30))

        with ThreadPoolExecutor(max_workers=2) as executor:
            claimed = tuple(executor.map(claim, ("worker-a", "worker-b")))
        assert sum(item is not None for item in claimed) == 1

        repository.append_event(
            run.id,
            "node.status",
            {
                "step_id": "postgres-parse-question",
                "node": "parse_question",
                "branch_id": None,
                "status": "completed",
                "attempt": 1,
                "summary": "Question classified.",
                "duration_ms": 1,
            },
            event_key="postgres-node",
        )
        reconstructed = ResearchRunRepository(build_session_factory(database_url))
        first_page = reconstructed.events_after(run.id, 0)
        assert first_page
        cursor = first_page[0].id
        assert all(event.id > cursor for event in reconstructed.events_after(run.id, cursor))

        repository.consume_rate_limit("actor", "test", limit=1, window_seconds=60)
        with pytest.raises(RateLimitExceededError):
            reconstructed.consume_rate_limit("actor", "test", limit=1, window_seconds=60)
    finally:
        ResearchRun.metadata.drop_all(engine, tables=reversed(TABLES))
        engine.dispose()
