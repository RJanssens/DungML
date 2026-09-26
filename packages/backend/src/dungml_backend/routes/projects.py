"""/projects — CRUD over the current user's projects."""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select

from .. import access, contract, defaults, models, schemas
from ..deps import CurrentUser, DbDep
from ..identity import display_name
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
    """The project if the caller owns it *or* is a member; 404 otherwise.

    Owner-only actions (delete, membership management) follow this with
    `access.require_owner`.
    """
    return access.get_project(db, project_id, user)


def _owner_label(proj: models.Project) -> str:
    u = proj.user
    return u.email or u.subject or ""


def _project_out(
    proj: models.Project, user: models.User
) -> schemas.ProjectOut:
    return schemas.ProjectOut(
        id=proj.id,
        name=proj.name,
        created_at=proj.created_at,
        updated_at=proj.updated_at,
        shared=proj.user_id != user.id,
        owner=_owner_label(proj),
    )


@router.get("", response_model=list[schemas.ProjectOut])
def list_projects(user: CurrentUser, db: DbDep) -> list[schemas.ProjectOut]:
    """Everything the caller owns or is a member of, most recent first."""
    return [_project_out(p, user) for p in access.list_projects(db, user)]


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
) -> schemas.ProjectOut:
    return _project_out(_get_owned(db, project_id, user), user)


@router.patch("/{project_id}", response_model=schemas.ProjectOut)
def update_project(
    project_id: str,
    body: schemas.ProjectIn,
    user: CurrentUser,
    db: DbDep,
) -> schemas.ProjectOut:
    proj = _get_owned(db, project_id, user)
    proj.name = body.name
    db.commit()
    db.refresh(proj)
    return _project_out(proj, user)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str, user: CurrentUser, db: DbDep
) -> None:
    """Owner-only — a member losing everyone's maps would be a bad surprise."""
    proj = access.require_owner(_get_owned(db, project_id, user), user)
    db.delete(proj)
    db.commit()


@router.get(
    "/{project_id}/campaigns", response_model=list[schemas.CampaignStateOut]
)
def list_campaigns(
    project_id: str, user: CurrentUser, db: DbDep
) -> list[schemas.CampaignStateOut]:
    """External campaigns linked to this project, and where each party stands.

    This is the GUI's window onto a running ttrpg2 game: which map it is on,
    the session carrying its fog, and how much of the map it has uncovered.
    Nothing here is authored state — it's all the play session's.
    """
    proj = _get_owned(db, project_id, user)
    out: list[schemas.CampaignStateOut] = []
    for link in contract.campaign_links_for_project(db, proj.id):
        row = schemas.CampaignStateOut(external_id=link.external_id)
        m = db.get(models.Map, link.active_map_id) if link.active_map_id else None
        if m is not None and m.project_id == proj.id:
            row.active_map_id = m.id
            row.active_map_name = m.name
            s = contract.campaign_session_for(db, m, link.external_id)
            row.session_id = s.id
            row.party_location = s.party_location
            row.discovered_nodes = len(s.discovered_nodes or [])
            row.discovered_doors = len(s.discovered_doors or [])
            row.total_nodes = contract.node_count(m)
            row.updated_at = s.updated_at
        out.append(row)
    return out


@router.get(
    "/{project_id}/sessions", response_model=list[schemas.SessionSummaryOut]
)
def list_project_sessions(
    project_id: str, user: CurrentUser, db: DbDep
) -> list[schemas.SessionSummaryOut]:
    """Every play session in the project, newest activity first.

    Progress per session already existed inside a map's play view; a GM with
    twenty maps had to open each one to find it. The node total is counted
    once per map that actually has sessions, so a project of mostly
    session-less maps costs nothing.
    """
    proj = _get_owned(db, project_id, user)
    out: list[schemas.SessionSummaryOut] = []
    totals: dict[str, int] = {}
    for m in proj.maps:
        if not m.play_sessions:
            continue
        totals[m.id] = contract.node_count(m)
        for s in m.play_sessions:
            out.append(
                schemas.SessionSummaryOut(
                    session_id=s.id,
                    name=s.name,
                    map_id=m.id,
                    map_name=m.name,
                    party_location=s.party_location,
                    discovered_nodes=len(s.discovered_nodes or []),
                    total_nodes=totals[m.id],
                    external_id=s.external_id,
                    updated_at=s.updated_at,
                )
            )
    out.sort(key=lambda r: r.updated_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


# ---- membership ----


@router.get("/{project_id}/members", response_model=list[schemas.MemberOut])
def list_members(
    project_id: str, user: CurrentUser, db: DbDep
) -> list[schemas.MemberOut]:
    """The project's members (not its owner — that's `ProjectOut.owner`).

    Visible to members as well as the owner: people working together on a
    project can see who else is on it.
    """
    proj = _get_owned(db, project_id, user)
    return [
        schemas.MemberOut(
            user_id=m.user_id, subject=m.user.subject or "", email=m.user.email or ""
        )
        for m in sorted(proj.members, key=lambda m: m.created_at)
    ]


@router.post(
    "/{project_id}/members", response_model=schemas.MemberOut, status_code=201
)
def add_member(
    project_id: str, body: schemas.MemberIn, user: CurrentUser, db: DbDep
) -> schemas.MemberOut:
    """Share the project with another user, named by subject or email.

    Idempotent — re-adding an existing member is a 201 with the same row, so
    a double-click can't 409 at the GM. 404 when nobody matches: creating an
    account from a typo'd address would be worse than the error.
    """
    proj = access.require_owner(_get_owned(db, project_id, user), user)
    target = access.find_user(db, body.identifier)
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"no user matching '{body.identifier}' — they must sign in once first",
        )
    if target.id == proj.user_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "that user already owns this project"
        )
    row = db.get(models.ProjectMember, (proj.id, target.id))
    if row is None:
        row = models.ProjectMember(project_id=proj.id, user_id=target.id)
        db.add(row)
        db.commit()
    return schemas.MemberOut(
        user_id=target.id, subject=target.subject or "", email=target.email or ""
    )


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_member(
    project_id: str, user_id: str, user: CurrentUser, db: DbDep
) -> None:
    """Revoke a membership. Owner-only; unknown membership is a 404."""
    proj = access.require_owner(_get_owned(db, project_id, user), user)
    row = db.get(models.ProjectMember, (proj.id, user_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not a member of this project")
    db.delete(row)
    db.commit()


# ---- project import / export (a zip archive with a custom extension) ----

# A project export is a ZIP (DEFLATE-compressed) holding one `.dmap` per map
# plus a manifest. The custom extension just brands the file; it's a normal
# zip inside, so it stays inspectable.
EXPORT_EXT = ".dmapproj"
EXPORT_FORMAT = "dungml-project"
EXPORT_VERSION = 1


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return s or "map"


@router.get("/{project_id}/export")
def export_project(project_id: str, user: CurrentUser, db: DbDep) -> Response:
    """Download the whole project (all its maps) as a single compressed
    `.dmapproj` archive that `import` can restore into a new project."""
    proj = _get_owned(db, project_id, user)
    maps = sorted(proj.maps, key=lambda m: m.created_at)
    manifest: dict = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "name": proj.name,
        "maps": [],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, m in enumerate(maps):
            fname = f"maps/{i:04d}_{_slug(m.name)}.dmap"
            z.writestr(fname, m.source or "")
            manifest["maps"].append({"name": m.name, "file": fname})
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    filename = f"{_slug(proj.name)}{EXPORT_EXT}"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=schemas.ProjectOut, status_code=201)
def import_project(
    user: CurrentUser, db: DbDep, file: UploadFile = File(...)
) -> models.Project:
    """Create a new project from an uploaded `.dmapproj` archive. The
    project's maps are restored verbatim; play-sessions are not included in
    exports, so a fresh import starts with none."""
    raw = file.file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="not a valid project archive",
        )
    try:
        manifest = json.loads(zf.read("manifest.json"))
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="archive is missing manifest.json",
        )
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="archive manifest is corrupt",
        )
    if not isinstance(manifest, dict) or manifest.get("format") != EXPORT_FORMAT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unrecognised project archive format",
        )
    proj = models.Project(
        user_id=user.id, name=str(manifest.get("name") or "Imported project")
    )
    db.add(proj)
    db.flush()
    for entry in manifest.get("maps", []):
        if not isinstance(entry, dict):
            continue
        fpath = entry.get("file")
        mname = str(entry.get("name") or "map")
        try:
            source = zf.read(fpath).decode("utf-8") if fpath else ""
        except (KeyError, UnicodeDecodeError):
            continue  # skip a missing/corrupt entry rather than fail wholesale
        db.add(models.Map(project_id=proj.id, name=mname, source=source))
    db.commit()
    defaults.ensure_project_default(db, proj.id)
    db.refresh(proj)
    return proj


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
    defaults.ensure_project_default(db, proj.id)
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
