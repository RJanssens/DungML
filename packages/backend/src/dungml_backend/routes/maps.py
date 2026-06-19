"""Maps — nested-create under /projects/{id}/maps, flat read/update/delete under /maps/{id}."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from .. import models, schemas
from ..deps import CurrentUser, DbDep

router = APIRouter(tags=["maps"])


def _get_owned_project(db, project_id: str, user: models.User) -> models.Project:
    proj = db.get(models.Project, project_id)
    if proj is None or proj.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="project not found"
        )
    return proj


def _get_owned_map(db, map_id: str, user: models.User) -> models.Map:
    m = db.get(models.Map, map_id)
    if m is None or m.project.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="map not found"
        )
    return m


@router.get(
    "/projects/{project_id}/maps",
    response_model=list[schemas.MapSummaryOut],
)
def list_maps(
    project_id: str, user: CurrentUser, db: DbDep
) -> list[models.Map]:
    _get_owned_project(db, project_id, user)
    rows = db.scalars(
        select(models.Map)
        .where(models.Map.project_id == project_id)
        .order_by(models.Map.updated_at.desc())
    ).all()
    return list(rows)


@router.post(
    "/projects/{project_id}/maps",
    response_model=schemas.MapOut,
    status_code=201,
)
def create_map(
    project_id: str,
    body: schemas.MapCreateIn,
    user: CurrentUser,
    db: DbDep,
) -> models.Map:
    proj = _get_owned_project(db, project_id, user)
    m = models.Map(project_id=proj.id, name=body.name, source=body.source)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.get("/maps/{map_id}", response_model=schemas.MapOut)
def get_map(map_id: str, user: CurrentUser, db: DbDep) -> models.Map:
    return _get_owned_map(db, map_id, user)


@router.put("/maps/{map_id}", response_model=schemas.MapOut)
def update_map(
    map_id: str,
    body: schemas.MapUpdateIn,
    user: CurrentUser,
    db: DbDep,
) -> models.Map:
    m = _get_owned_map(db, map_id, user)
    if body.name is not None:
        m.name = body.name
    if body.source is not None:
        m.source = body.source
    db.commit()
    db.refresh(m)
    return m


@router.delete("/maps/{map_id}", status_code=204)
def delete_map(map_id: str, user: CurrentUser, db: DbDep) -> None:
    m = _get_owned_map(db, map_id, user)
    db.delete(m)
    db.commit()
