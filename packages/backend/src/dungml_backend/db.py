"""SQLAlchemy engine, session factory, base class.

The engine and session factory are lazy so test code can override
`config.settings.db_url` before they're first touched.
"""
from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config


class Base(DeclarativeBase):
    """Common declarative base."""


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        connect_args = {}
        if config.settings.db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(
            config.settings.db_url, future=True, connect_args=connect_args
        )
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), expire_on_commit=False, future=True
        )
    return _SessionLocal


def session_dep() -> Iterator[Session]:
    """FastAPI dependency yielding a DB session that auto-closes."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:
    """Test helper: drop cached engine/sessionmaker so the next access re-reads
    `config.settings.db_url`."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def init_schema() -> None:
    """Create all tables. Idempotent."""
    # Import here so all models register on Base.metadata before create_all.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())
