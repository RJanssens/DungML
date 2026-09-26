"""ORM models — users, projects, maps, play-sessions."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator):
    """A timestamp that is UTC in Python and stored the way it always was.

    SQLite keeps no timezone, so timestamps are stored as naive UTC by
    convention — and used to come back naive, which reached clients as
    `"…T12:43:41"` with no offset. ISO 8601 reads that as *local* time, so the
    web app showed every change hours old. Values read back are marked UTC
    here, once, instead of at every place a timestamp is serialised.

    SQLite storage is unchanged (naive UTC), so rows written before and after
    this type look the same. Backends that keep a timezone get an aware value.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)   # naive means UTC here
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _now() -> datetime:
    # Aware UTC, so an object that hasn't been reloaded since its default
    # fired says the same thing as one read back through UTCDateTime.
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # The IdP's `sub` claim — how a bearer token resolves to this row.
    # Nullable because rows created before the OIDC migration have no
    # subject: they exist, own projects, and can never be authenticated as.
    # `adopt.py` is how those projects get a reachable owner. (Both SQLite
    # and Postgres allow repeated NULLs under a unique index.)
    subject: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, default=None
    )
    email: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)

    projects: Mapped[list["Project"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    # Public: every signed-in user gets member rights (see access.py). New
    # projects default to it; the service and example projects opt out.
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_now, onupdate=_now
    )

    user: Mapped[User] = relationship(back_populates="projects")
    maps: Mapped[list["Map"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(Base):
    """A user other than the owner who may work on a project.

    Projects started single-owner (`projects.user_id`); this adds co-access
    without changing that column, so the owner stays unambiguous. Members get
    everything the owner gets except deleting the project and managing its
    membership — see `access.py`.
    """

    __tablename__ = "project_members"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class Map(Base):
    __tablename__ = "maps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, default=None
    )
    source: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_now, onupdate=_now
    )

    project: Mapped[Project] = relationship(back_populates="maps")
    play_sessions: Mapped[list["PlaySession"]] = relationship(
        back_populates="map", cascade="all, delete-orphan"
    )

    @property
    def kind(self) -> str:
        """Derived classification — content-only, no schema column.

        A `.dmap` file with no top-level `map "..."` block is a *library*
        (include-only): it ships feature_defs / rooms / corridors that other
        maps pull in via `include "name.dmap"`. Everything else is a
        renderable *map*.
        """
        return "library" if 'map "' not in (self.source or "") else "map"


class PlaySession(Base):
    """A single play-through's runtime overlay on a map.

    The map's `.dmap` source is authored DM truth and never mutates during
    play. A PlaySession records what *this* party has discovered and the
    runtime state of doors, so exploration, fog-of-war and discovery-aware
    pathfinding can be tracked without touching the authored map. The
    derived connectivity graph (rooms/corridors as nodes, doors as edges)
    is recomputed from the map source on demand — see `dungml.graph`.
    """

    __tablename__ = "play_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    map_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("maps.id", ondelete="CASCADE"), index=True
    )
    # Set for authored-map play (sub-project B): the ttrpg3 campaign this
    # session's fog belongs to. NULL for legacy service-owned maps (one
    # session per map). The get-or-create key becomes (map_id, external_id).
    external_id: Mapped[str | None] = mapped_column(
        String(255), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    # Authoritative party position — a node id like "room.antechamber".
    party_location: Mapped[str | None] = mapped_column(String(255), default=None)
    # Discovery overlay. Stored as JSON so the shape can evolve without a
    # migration: node ids seen, door keys seen, and per-door runtime state
    # overrides (door_key -> "open" | "locked" | ...).
    discovered_nodes: Mapped[list] = mapped_column(JSON, default=list)
    discovered_doors: Mapped[list] = mapped_column(JSON, default=list)
    door_states: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_now, onupdate=_now
    )

    map: Mapped[Map] = relationship(back_populates="play_sessions")


class CampaignLink(Base):
    """Links an external ttrpg3 campaign (external_id) to a GM-owned Project.
    The GM authorizes the link with their own token; the service then operates
    on that project's maps on the campaign's behalf (sub-project B)."""

    __tablename__ = "campaign_links"

    external_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE")
    )
    # Which of the project's maps the campaign is playing on right now.
    # ttrpg2 keeps the authoritative copy in its own state; it reports the
    # choice here so the web app can point the GM at the live session
    # instead of making them guess which map is in play. ON DELETE SET NULL:
    # deleting a map must not take the link with it.
    active_map_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("maps.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
