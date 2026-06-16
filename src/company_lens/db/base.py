from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from company_lens.db import models as models  # noqa: E402,F401
