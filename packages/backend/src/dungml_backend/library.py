"""Project-owned include library helpers.

Every project owns an editable copy of the built-in feature library,
stored as an ordinary `library` map named ``core.dmap``. Maps in the
project bring it in with ``include "core.dmap"``; resolution prefers the
project's copy over the bundled one (see `project_include_sources`), so
a user can edit or extend the built-ins without touching the package.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from dungml import library_source, list_libraries

from . import models

# The include name maps reference and the display name of the seeded map.
CORE_MAP_NAME = "core.dmap"


def core_source() -> str:
    """Snapshot of the bundled core.dmap, copied into new projects."""
    return library_source(CORE_MAP_NAME) or ""


def seed_core_map(db: Session, project: models.Project) -> models.Map:
    """Add a project-owned copy of core.dmap. Caller commits."""
    m = models.Map(
        project_id=project.id, name=CORE_MAP_NAME, source=core_source()
    )
    db.add(m)
    return m


def project_include_sources(
    db: Session, project_id: str, *, exclude_map_id: str | None = None
) -> dict[str, str]:
    """Map every sibling map's name -> source for include resolution.

    Passed to `dungml.parse(..., include_sources=...)` so a map's
    `include "core.dmap"` resolves to the project's own copy. The map
    being rendered is excluded by id so its (possibly unsaved) source
    doesn't shadow itself.
    """
    rows = db.scalars(
        select(models.Map).where(models.Map.project_id == project_id)
    ).all()
    out: dict[str, str] = {}
    for m in rows:
        if exclude_map_id is not None and m.id == exclude_map_id:
            continue
        out[m.name] = m.source
    return out


class UnknownLibrary(Exception):
    """Requested bundled library name doesn't exist."""


class LibraryAlreadyImported(Exception):
    """The project already has a map of that name."""


def library_catalog(db: Session, project_id: str) -> list[tuple[str, bool]]:
    """(name, already_in_project) for every bundled include library."""
    present = set(
        db.scalars(
            select(models.Map.name).where(
                models.Map.project_id == project_id
            )
        ).all()
    )
    return [(name, name in present) for name in list_libraries()]


def import_bundled_library(
    db: Session, project: models.Project, name: str
) -> models.Map:
    """Copy a bundled library's current content into the project as an
    editable library map. Caller commits.

    Raises UnknownLibrary if `name` isn't bundled, LibraryAlreadyImported
    if the project already has a map of that name (we never clobber edits).
    """
    src = library_source(name)
    if src is None or name not in set(list_libraries()):
        raise UnknownLibrary(name)
    exists = db.scalar(
        select(models.Map.id).where(
            models.Map.project_id == project.id, models.Map.name == name
        )
    )
    if exists is not None:
        raise LibraryAlreadyImported(name)
    m = models.Map(project_id=project.id, name=name, source=src)
    db.add(m)
    return m


def backfill_core_maps(db: Session) -> int:
    """Add a core.dmap to every project that lacks one. Returns the count.

    Idempotent — run at startup so projects created before core.dmap was
    seeded gain their editable copy. Commits if anything changed.
    """
    have = set(
        db.scalars(
            select(models.Map.project_id).where(
                models.Map.name == CORE_MAP_NAME
            )
        ).all()
    )
    missing = db.scalars(
        select(models.Project).where(models.Project.id.notin_(have))
        if have
        else select(models.Project)
    ).all()
    src = core_source()
    for proj in missing:
        db.add(models.Map(project_id=proj.id, name=CORE_MAP_NAME, source=src))
    if missing:
        db.commit()
    return len(missing)
