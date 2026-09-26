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


def ensure_columns() -> None:
    """ALTER-add columns that create_all won't add to pre-existing tables.

    dungml has no Alembic; create_all creates missing tables but never
    alters existing ones. Idempotent — safe to call every startup.
    """
    from sqlalchemy import inspect, text

    engine = get_engine()
    insp = inspect(engine)
    existing = set(insp.get_table_names())

    def cols(table: str) -> set[str]:
        return {c["name"] for c in insp.get_columns(table)}

    if "maps" in existing and "is_default" not in cols("maps"):
        lit = "0" if engine.dialect.name == "sqlite" else "false"
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"ALTER TABLE maps ADD COLUMN is_default "
                    f"BOOLEAN NOT NULL DEFAULT {lit}"
                )
            )

    # The map contract keys a Map (and a per-campaign PlaySession) by the
    # caller's external id. Both arrived after the original tables, so a DB
    # created before the contract lands here missing them and every
    # /maps/{external_id} and /campaigns/… route 500s on first query.
    # Nullable, so a plain ADD COLUMN is enough; the unique index on
    # maps.external_id is created separately (create_all only indexes
    # tables it creates itself).
    for table, column in (("maps", "external_id"), ("play_sessions", "external_id")):
        if table in existing and column not in cols(table):
            with engine.begin() as conn:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(255)")
                )

    # The GUI needs to know which map an external campaign is playing on.
    # Added after campaign_links shipped, so an existing DB needs the column.
    # Plain nullable VARCHAR — SQLite can't add a column with a FK reference,
    # and the app treats a dangling id as "no active map" anyway.
    if "campaign_links" in existing and "active_map_id" not in cols("campaign_links"):
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE campaign_links ADD COLUMN active_map_id VARCHAR(36)")
            )

    if "maps" in existing:
        idx = {i["name"] for i in insp.get_indexes("maps")}
        if "ix_maps_external_id" not in idx:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_maps_external_id "
                        "ON maps (external_id)"
                    )
                )

    # Public projects. Adding the column makes every existing project public
    # (the DEFAULT), then — in this branch only, so exactly once — the two
    # kinds that should not be are set private: the ttrpg2 service project
    # (ttrpg2 rewrites those maps on every token move) and each user's example
    # project (one identical copy per user). Doing it on every boot would undo
    # an owner who later made one of them public.
    if "projects" in existing and "is_public" not in cols("projects"):
        from .contract import _SERVICE_PROJECT, _SERVICE_SUBJECT
        from .samples import EXAMPLE_PROJECT_NAME

        sqlite = engine.dialect.name == "sqlite"
        yes, no = ("1", "0") if sqlite else ("true", "false")
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE projects ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT {yes}")
            )
            conn.execute(
                text(
                    f"UPDATE projects SET is_public = {no} WHERE name = :example "
                    "OR (name = :service AND user_id IN "
                    "(SELECT id FROM users WHERE subject = :subject))"
                ),
                {"example": EXAMPLE_PROJECT_NAME, "service": _SERVICE_PROJECT,
                 "subject": _SERVICE_SUBJECT},
            )
