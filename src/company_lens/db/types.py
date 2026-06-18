from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import UserDefinedType


class PgVector(UserDefinedType[Sequence[float]]):
    """Minimal pgvector SQLAlchemy type without requiring the pgvector Python package."""

    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:
        if dimensions is not None and dimensions <= 0:
            raise ValueError("dimensions must be positive.")
        self.dimensions = dimensions

    def get_col_spec(self, **_: Any) -> str:
        if self.dimensions is None:
            return "vector"
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect: Dialect) -> Callable[[Sequence[float] | None], str | None]:
        def process(value: Sequence[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(str(float(item)) for item in value) + "]"

        return process

    def result_processor(
        self,
        dialect: Dialect,
        coltype: object,
    ) -> Callable[[object], list[float] | None]:
        def process(value: object) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(item) for item in value]
            if isinstance(value, tuple):
                return [float(item) for item in value]
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned.startswith("[") and cleaned.endswith("]"):
                    cleaned = cleaned[1:-1]
                if not cleaned:
                    return []
                return [float(item) for item in cleaned.split(",")]
            raise TypeError(f"Unsupported pgvector value: {type(value)!r}")

        return process
