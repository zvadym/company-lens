from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from company_lens.observability.telemetry import instrument_sqlalchemy


def build_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url, pool_pre_ping=True)
    instrument_sqlalchemy(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
