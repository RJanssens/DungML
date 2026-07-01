"""ttrpg3↔dungml campaign/multi-map contract (root-mounted: /campaigns/…).

Links an external campaign to a GM-owned project. link/unlink are GM-user
authorized; enumeration/render/reveal are service-scoped and bounded to linked
projects. Parallel to and independent of the legacy /maps/{external_id} routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from .. import contract, models
from ..deps import CurrentService, CurrentUser, DbDep

router = APIRouter(tags=["campaigns"])


class LinkIn(BaseModel):
    project_id: str


@router.post("/campaigns/{external_id}/link")
def link(external_id: str, body: LinkIn, user: CurrentUser, db: DbDep) -> dict:
    proj = db.get(models.Project, body.project_id)
    if proj is None or proj.user_id != user.id:
        # Treat unauthorized the same as missing — don't leak existence.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    contract.link_campaign(db, external_id, proj)
    return {"external_id": external_id, "project_id": proj.id}


@router.delete("/campaigns/{external_id}/link", status_code=204)
def unlink(external_id: str, user: CurrentUser, db: DbDep) -> None:
    link_row = db.get(models.CampaignLink, external_id)
    if link_row is None:
        return  # idempotent
    proj = db.get(models.Project, link_row.project_id)
    if proj is not None and proj.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    db.delete(link_row)
    db.commit()


@router.get("/campaigns/{external_id}/maps")
def list_maps(external_id: str, _svc: CurrentService, db: DbDep) -> list[dict]:
    proj = contract.linked_project(db, external_id)
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "campaign not linked")
    renderable = [m for m in proj.maps if m.kind == "map"]
    renderable.sort(key=lambda m: m.updated_at, reverse=True)
    return [{"id": m.id, "name": m.name} for m in renderable]
