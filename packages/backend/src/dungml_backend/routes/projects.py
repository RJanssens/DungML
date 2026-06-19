"""/projects — CRUD over the current user's projects."""
from __future__ import annotations

import io
import json
import re
import zipfile

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response
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
