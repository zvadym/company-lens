from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


@dataclass(frozen=True)
class DatabaseHealth:
    status: Literal["ok", "error"]
    latency_ms: float | None = None
    detail: str | None = None


def check_database(database_url: str) -> DatabaseHealth:
    start = perf_counter()
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        latency_ms = round((perf_counter() - start) * 1000, 2)
        return DatabaseHealth(status="ok", latency_ms=latency_ms)
    except SQLAlchemyError as exc:
        return DatabaseHealth(status="error", detail=exc.__class__.__name__)
    finally:
        if "engine" in locals():
            engine.dispose()
