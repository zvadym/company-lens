from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import UserDefinedType


class PgVector(UserDefinedType[Sequence[float]]):
    """Minimal pgvector SQLAlchemy type without requiring the pgvector Python package."""

    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "vector"

    def bind_processor(self, dialect: Dialect) -> Callable[[Sequence[float] | None], str | None]:
        def process(value: Sequence[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(str(float(item)) for item in value) + "]"

        return process
