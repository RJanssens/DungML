"""ORM models — users, projects, maps, play-sessions."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    # Naive UTC. SQLite (and many other backends) doesn't carry tz info
    # across a round-trip, so we standardize the storage representation
    # and treat all timestamps as UTC by convention.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    user: Mapped[User] = relationship(back_populates="projects")
    maps: Mapped[list["Map"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
