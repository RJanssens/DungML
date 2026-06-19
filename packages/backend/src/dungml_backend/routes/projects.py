"""/projects — CRUD over the current user's projects."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from .. import models, schemas
from ..deps import CurrentUser, DbDep
from ..library import (
    LibraryAlreadyImported,
    UnknownLibrary,
    import_bundled_library,
    library_catalog,
    seed_core_map,
)
from ..samples import EXAMPLE_PROJECT_NAME, SAMPLE_MAPS

router = APIRouter(prefix="/projects", tags=["projects"])


def _get_owned(
    db, project_id: str, user: models.User
) -> models.Project:
    proj = db.get(models.Project, project_id)
    if proj is None or proj.user_id != user.id:
        # Treat unauthorized access the same as missing — don't leak existence.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="project not found"
        )
    return proj


@router.get("", response_model=list[schemas.ProjectOut])
def list_projects(user: CurrentUser, db: DbDep) -> list[models.Project]:
    rows = db.scalars(
        select(models.Project)
        .where(models.Project.user_id == user.id)
        .order_by(models.Project.updated_at.desc())
    ).all()
    return list(rows)


@router.post("", response_model=schemas.ProjectOut, status_code=201)
def create_project(
    body: schemas.ProjectIn, user: CurrentUser, db: DbDep
) -> models.Project:
    proj = models.Project(user_id=user.id, name=body.name)
    db.add(proj)
    db.flush()
    seed_core_map(db, proj)
    db.commit()
    db.refresh(proj)
    return proj


@router.get("/{project_id}", response_model=schemas.ProjectOut)
def get_project(
    project_id: str, user: CurrentUser, db: DbDep
) -> models.Project:
    return _get_owned(db, project_id, user)


@router.patch("/{project_id}", response_model=schemas.ProjectOut)
def update_project(
    project_id: str,
    body: schemas.ProjectIn,
    user: CurrentUser,
    db: DbDep,
) -> models.Project:
    proj = _get_owned(db, project_id, user)
    proj.name = body.name
    db.commit()
    db.refresh(proj)
    return proj


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str, user: CurrentUser, db: DbDep
) -> None:
    proj = _get_owned(db, project_id, user)
    db.delete(proj)
    db.commit()


@router.post("/import-samples", response_model=schemas.ProjectOut, status_code=201)
def import_samples(user: CurrentUser, db: DbDep) -> models.Project:
    """Create a project pre-populated with the bundled .dmap samples.

    Returns the new project. If no samples are available on disk this
    still creates an empty project, so the client always gets something
    to navigate into.
    """
    proj = models.Project(user_id=user.id, name=EXAMPLE_PROJECT_NAME)
    db.add(proj)
    db.flush()
    seed_core_map(db, proj)
    for sample in SAMPLE_MAPS:
        db.add(
            models.Map(
                project_id=proj.id, name=sample.name, source=sample.source
            )
        )
    db.commit()
    db.refresh(proj)
    return proj


@router.get(
    "/{project_id}/library-catalog",
    response_model=list[schemas.LibraryCatalogEntry],
)
def get_library_catalog(
    project_id: str, user: CurrentUser, db: DbDep
) -> list[schemas.LibraryCatalogEntry]:
    """Bundled include libraries and whether this project already has each.

    Powers the project's "Add library" picker."""
    proj = _get_owned(db, project_id, user)
    return [
        schemas.LibraryCatalogEntry(name=name, added=added)
        for name, added in library_catalog(db, proj.id)
    ]


@router.post(
    "/{project_id}/import-library",
    response_model=schemas.MapOut,
    status_code=201,
)
def import_library(
    project_id: str,
    body: schemas.ImportLibraryIn,
    user: CurrentUser,
    db: DbDep,
) -> models.Map:
    """Copy a bundled include library into the project as an editable
    library map, so it can be viewed and edited centrally."""
    proj = _get_owned(db, project_id, user)
    try:
        m = import_bundled_library(db, proj, body.name)
    except UnknownLibrary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no bundled library named '{body.name}'",
        )
    except LibraryAlreadyImported:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"project already has a map named '{body.name}'",
        )
    db.commit()
    db.refresh(m)
    return m
