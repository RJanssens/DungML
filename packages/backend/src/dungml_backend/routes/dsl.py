"""/dsl — stateless parse/validate/render, plus by-map convenience routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from dungml import (
    DmapParseError,
    Diagnostic,
    build_graph,
    feature_def_origins,
    list_renderers,
    parse,
    render as do_render,
    validate,
)

from .. import models, schemas
from ..deps import CurrentUser, DbDep
from ..library import project_include_sources

router = APIRouter(prefix="/dsl", tags=["dsl"])
map_render_router = APIRouter(tags=["maps"])  # mounted at root


# ----- helpers -----

def _diag(d: Diagnostic) -> schemas.DiagnosticOut:
    return schemas.DiagnosticOut(
        severity=d.severity,
        message=d.message,
        line=d.line,
        column=d.column,
        end_line=d.end_line,
        end_column=d.end_column,
    )


def _parse_error_response(e: DmapParseError) -> dict:
    return {
        "detail": {
            "message": e.message,
            "line": e.line,
            "column": e.column,
        }
    }


# ----- stateless DSL ops -----

@router.get("/renderers", response_model=list[str])
def renderers() -> list[str]:
    return list_renderers()


@router.post("/parse")
def parse_source(body: schemas.SourceIn) -> dict:
    """Parse and return the typed model as JSON."""
    try:
        m = parse(body.source)
    except DmapParseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": e.message, "line": e.line, "column": e.column,
            },
        )
    return {"map": m.model_dump()}


@router.post("/validate", response_model=schemas.ValidateOut)
def validate_source(body: schemas.SourceIn) -> schemas.ValidateOut:
    try:
        m = parse(body.source)
    except DmapParseError as e:
        # Parse failures returned as a single error diagnostic so the
        # editor can render a single 'red squiggle' without a second call.
        return schemas.ValidateOut(diagnostics=[
            schemas.DiagnosticOut(
                severity="error", message=e.message,
                line=e.line, column=e.column,
                end_line=e.end_line or e.line,
                end_column=e.end_column or e.column,
            )
        ])
    return schemas.ValidateOut(diagnostics=[_diag(d) for d in validate(m)])


@router.post("/render")
def render_source(body: schemas.RenderIn):
    try:
        m = parse(body.source)
    except DmapParseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": e.message, "line": e.line, "column": e.column,
            },
        )
    diags = validate(m)
    try:
        svg = do_render(m, body.renderer)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return schemas.RenderOut(
        svg=svg, diagnostics=[_diag(d) for d in diags]
    )


@router.post("/connectivity", response_model=schemas.ConnectivityOut)
def connectivity_source(body: schemas.SourceIn) -> schemas.ConnectivityOut:
    """Per-node connectivity for the editor's pathing check.

    A room/corridor is `connected` when at least one door touches it — an
    edge to another node or a boundary exit. Isolated nodes (no doors) come
    back `connected=False` so the editor can flag them.
    """
    try:
        m = parse(body.source)
    except DmapParseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": e.message, "line": e.line, "column": e.column},
        )
    g = build_graph(m)
    nodes: list[schemas.NodeConnectivity] = []
    for nid, node in g.nodes.items():
        conns: list[schemas.NodeConnection] = []
        # Every door touching the node (either side), so the far side of a
        # one-way door still reads as connected.
        for e in g.edges:
            if nid not in (e.a, e.b):
                continue
            if e.one_way:
                direction = "out" if nid == e.a else "in"
            else:
                direction = "both"
            conns.append(
                schemas.NodeConnection(
                    to=e.other(nid), type=e.type, state=e.state,
                    direction=direction,
                )
            )
        for b in g.boundary_exits(nid):
            conns.append(
                schemas.NodeConnection(
                    to="(exterior)", type=b.type, state=b.state, direction="out",
                )
            )
        nodes.append(
            schemas.NodeConnectivity(
                id=nid, kind=node.kind, name=node.name,
                connected=len(conns) > 0, doors=len(conns), connections=conns,
            )
        )
    return schemas.ConnectivityOut(nodes=nodes)


# ----- by-stored-map convenience routes -----

def _get_owned_map(db, map_id: str, user) -> models.Map:
    m = db.get(models.Map, map_id)
    if m is None or m.project.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="map not found"
        )
    return m


def _validate_in_project(source: str, db, m: models.Map) -> schemas.ValidateOut:
    """Validate `source` as if it were map `m`, resolving includes (e.g.
    `include "core.dmap"`) against the project's own maps."""
    inc = project_include_sources(db, m.project_id, exclude_map_id=m.id)
    try:
        parsed = parse(source, include_sources=inc)
    except DmapParseError as e:
        return schemas.ValidateOut(diagnostics=[
            schemas.DiagnosticOut(
                severity="error", message=e.message,
                line=e.line, column=e.column,
                end_line=e.end_line or e.line,
                end_column=e.end_column or e.column,
            )
        ])
    return schemas.ValidateOut(diagnostics=[_diag(d) for d in validate(parsed)])


def _render_in_project(
    source: str, renderer: str | None, db, m: models.Map
) -> str:
    """Render `source` as map `m`, resolving includes against the project."""
    inc = project_include_sources(db, m.project_id, exclude_map_id=m.id)
    try:
        parsed = parse(source, include_sources=inc)
    except DmapParseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": e.message, "line": e.line, "column": e.column},
        )
    try:
        return do_render(parsed, renderer)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@map_render_router.get(
    "/maps/{map_id}/validate", response_model=schemas.ValidateOut,
)
def validate_stored_map(
    map_id: str, user: CurrentUser, db: DbDep,
) -> schemas.ValidateOut:
    m = _get_owned_map(db, map_id, user)
    return _validate_in_project(m.source, db, m)


@map_render_router.post(
    "/maps/{map_id}/validate", response_model=schemas.ValidateOut,
)
def validate_map_source(
    map_id: str, body: schemas.MapValidateIn, user: CurrentUser, db: DbDep,
) -> schemas.ValidateOut:
    """Validate a live editor buffer against the project's includes.

    `body.source` is the unsaved editor contents; falls back to the
    stored source when omitted."""
    m = _get_owned_map(db, map_id, user)
    return _validate_in_project(
        m.source if body.source is None else body.source, db, m
    )


@map_render_router.post(
    "/maps/{map_id}/feature-names", response_model=schemas.FeatureNamesOut,
)
def map_feature_names(
    map_id: str, body: schemas.MapValidateIn, user: CurrentUser, db: DbDep,
) -> schemas.FeatureNamesOut:
    """Feature_def names available to this map, grouped by source file.

    Resolves the map's includes against the project (so `core.dmap`,
    `outdoor.dmap`, etc. contribute their defs). `names` is the flat sorted
    union; `groups` splits them by the file that defines each (each include
    filename, plus a local group), with groups and names sorted
    alphabetically. On a parse error both come back empty, leaving the
    editor's dropdown on its last good value."""
    m = _get_owned_map(db, map_id, user)
    source = m.source if body.source is None else body.source
    inc = project_include_sources(db, m.project_id, exclude_map_id=m.id)
    origins = feature_def_origins(source, include_sources=inc)

    by_source: dict[str, list[str]] = {}
    for fname, src_file in origins.items():
        by_source.setdefault(src_file, []).append(fname)
    groups = [
        schemas.FeatureGroup(
            source=src_file, names=sorted(by_source[src_file], key=str.lower)
        )
        for src_file in sorted(by_source, key=str.lower)
    ]
    return schemas.FeatureNamesOut(
        names=sorted(origins.keys(), key=str.lower), groups=groups
    )


@map_render_router.get("/maps/{map_id}/render")
def render_stored_map(
    map_id: str,
    user: CurrentUser,
    db: DbDep,
    renderer: str | None = None,
) -> Response:
    m = _get_owned_map(db, map_id, user)
    svg = _render_in_project(m.source, renderer, db, m)
    return Response(content=svg, media_type="image/svg+xml")


@map_render_router.post("/maps/{map_id}/render", response_model=schemas.RenderOut)
def render_map_source(
    map_id: str, body: schemas.MapRenderIn, user: CurrentUser, db: DbDep,
) -> schemas.RenderOut:
    """Render a live editor buffer against the project's includes.

    Returns SVG + diagnostics (unlike the GET, which serves raw SVG) so
    the editor preview gets both in one round-trip."""
    m = _get_owned_map(db, map_id, user)
    source = m.source if body.source is None else body.source
    inc = project_include_sources(db, m.project_id, exclude_map_id=m.id)
    try:
        parsed = parse(source, include_sources=inc)
    except DmapParseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": e.message, "line": e.line, "column": e.column},
        )
    diags = validate(parsed)
    try:
        svg = do_render(parsed, body.renderer)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    return schemas.RenderOut(svg=svg, diagnostics=[_diag(d) for d in diags])
