"""Per-project default renderable-map designation.

A project may mark exactly one of its renderable maps (`kind == "map"`) as
the default. ttrpg3 renders that default when a linked campaign has no
explicitly-chosen active map. Libraries (`kind == "library"`) are never
eligible. Callers pass an open Session; these helpers commit.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models


def _renderable_maps(db: Session, project_id: str) -> list[models.Map]:
    rows = db.scalars(
        select(models.Map)
        .where(models.Map.project_id == project_id)
        .order_by(models.Map.created_at.asc(), models.Map.id.asc())
    ).all()
    return [m for m in rows if m.kind == "map"]


def set_default_map(db: Session, project_id: str, map_id: str) -> models.Map:
    """Mark map_id as the project's sole default renderable map.

    Clears the flag on every sibling renderable map. Raises ValueError if
    map_id is not a renderable map belonging to this project.
    """
    renderable = _renderable_maps(db, project_id)
    target = next((m for m in renderable if m.id == map_id), None)
    if target is None:
        raise ValueError("not a renderable map in this project")
    for m in renderable:
        m.is_default = m.id == map_id
    db.commit()
    db.refresh(target)
    return target


def ensure_project_default(db: Session, project_id: str) -> models.Map | None:
    """If the project has renderable maps but none is default, mark the
    earliest-created one. Idempotent; commits only on change."""
    renderable = _renderable_maps(db, project_id)
    if not renderable:
        return None
    current = next((m for m in renderable if m.is_default), None)
    if current is not None:
        return current
    renderable[0].is_default = True
    db.commit()
    db.refresh(renderable[0])
    return renderable[0]
