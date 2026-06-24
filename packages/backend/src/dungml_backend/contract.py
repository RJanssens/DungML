# packages/backend/src/dungml_backend/contract.py
"""Lazy provisioning for the map contract: one service user owns a shared
service project; each external_id (ttrpg3 instance_id) maps to one Map + one
PlaySession. Idempotent get-or-create."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import models

_SERVICE_SUBJECT = "@dungeon-daemon-service"
_SERVICE_PROJECT = "dungeon-daemon (service)"


def _service_user(db: DbSession) -> models.User:
    u = db.scalar(select(models.User).where(models.User.subject == _SERVICE_SUBJECT))
    if u is None:
        u = models.User(subject=_SERVICE_SUBJECT, email="service@dungml.local")
        db.add(u); db.commit(); db.refresh(u)
    return u


def _service_project(db: DbSession) -> models.Project:
    u = _service_user(db)
    p = db.scalar(
        select(models.Project).where(
            models.Project.user_id == u.id, models.Project.name == _SERVICE_PROJECT
        )
    )
    if p is None:
        p = models.Project(user_id=u.id, name=_SERVICE_PROJECT)
        db.add(p); db.commit(); db.refresh(p)
    return p


def get_or_create_map(db: DbSession, external_id: str) -> models.Map:
    m = db.scalar(select(models.Map).where(models.Map.external_id == external_id))
    if m is None:
        p = _service_project(db)
        m = models.Map(project_id=p.id, name=f"instance {external_id}",
                        source="", external_id=external_id)
        db.add(m); db.commit(); db.refresh(m)
        session_for(db, m)  # ensure a play session exists
    return m


def session_for(db: DbSession, m: models.Map) -> models.PlaySession:
    s = db.scalar(select(models.PlaySession).where(models.PlaySession.map_id == m.id))
    if s is None:
        s = models.PlaySession(map_id=m.id, name="party")
        db.add(s); db.commit(); db.refresh(s)
    return s
