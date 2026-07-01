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


def link_campaign(db: DbSession, external_id: str, project: models.Project) -> models.CampaignLink:
    """Upsert the campaign→project link. Caller must have verified ownership."""
    link = db.get(models.CampaignLink, external_id)
    if link is None:
        link = models.CampaignLink(
            external_id=external_id, project_id=project.id, user_id=project.user_id
        )
        db.add(link)
    else:
        link.project_id = project.id
        link.user_id = project.user_id
    db.commit()
    db.refresh(link)
    return link


def linked_project(db: DbSession, external_id: str) -> models.Project | None:
    link = db.get(models.CampaignLink, external_id)
    if link is None:
        return None
    return db.get(models.Project, link.project_id)


def map_in_link(db: DbSession, external_id: str, map_id: str) -> models.Map | None:
    """The Map iff external_id is linked and map_id belongs to that project."""
    proj = linked_project(db, external_id)
    if proj is None:
        return None
    m = db.get(models.Map, map_id)
    if m is None or m.project_id != proj.id:
        return None
    return m


def campaign_session_for(db: DbSession, m: models.Map, external_id: str) -> models.PlaySession:
    """Get-or-create the per-campaign PlaySession for an authored map. Keyed by
    (map_id, external_id) so each campaign carries its own fog."""
    s = db.scalar(
        select(models.PlaySession).where(
            models.PlaySession.map_id == m.id,
            models.PlaySession.external_id == external_id,
        )
    )
    if s is None:
        s = models.PlaySession(map_id=m.id, external_id=external_id, name="party")
        db.add(s); db.commit(); db.refresh(s)
    return s
