"""MCP server exposing dungml's project/map CRUD and DSL render.

The server reuses the dungml-backend ORM models and SQLite DB, so maps
created via MCP show up in the web GUI and vice versa, scoped to a
single "MCP user" account (configurable via env vars).

Tools exposed (FastMCP, stdio transport by default):

- `list_projects`                            → all projects owned by the MCP user
- `create_project(name)`                     → returns the new id
- `delete_project(project_id)`               → deletes a project + its maps
- `list_maps(project_id)`                    → maps in the project (no source)
- `create_map(project_id, name, source?)`    → returns the new id
- `get_map(map_id)`                          → returns the stored source
- `update_map(map_id, name?, source?)`       → patch one or both
- `delete_map(map_id)`
- `render_map(map_id?, source?, renderer?)`  → SVG string (one of id/source)
- `validate_source(source)`                  → list of diagnostics

Structured-authoring tools (grow a map by describing geometry relative to
what's there — placement maths runs server-side, the model never invents
coordinates; edits are appended and re-validated before saving):

- `add_room(map_id, name, width, height, direction?, anchor?, position?, gap?, ...)`
- `add_corridor(map_id, name, from_node, to_node, width?, ...)`
- `add_door(map_id, between? | (position, connects), type?, state?, ...)`

  Each accepts `discover_in_session` to reveal the new geometry in a
  play-session (the "party as cartographer" build-as-you-go flow).

Play-session tools (per-playthrough exploration state on top of a map —
discovery, fog-of-war, door state, and discovery-aware pathfinding; the
authored `.dmap` source never mutates, the connectivity graph is derived
on demand from it — see `dungml.graph`):

- `create_session(map_id, name, start_location?)`     → new session state
- `list_sessions(map_id)` / `get_session(session_id)` / `delete_session(session_id)`
- `set_party_location(session_id, location)`          → move party (reveals node)
- `mark_discovered(session_id, node, reveal_doors?)`  → reveal a room/corridor
- `mark_door(session_id, door, discovered?, state?)`  → find / open / unlock a door
- `get_exits(session_id, node, mode?)`                → ways out of a room
- `find_path(session_id, from, to, mode?)`            → server-side BFS route
- `get_known_map(session_id)`                         → discovered subgraph + frontier
- `render_session(session_id, mode?, renderer?)`      → fog-of-war or full SVG

Run with:

    uv run dmap-mcp

Env vars:
- DUNGML_DB_URL              same SQLite/Postgres URL the backend uses
- DUNGML_MCP_USER_EMAIL      default "mcp@local" — owner of MCP-created data
- DUNGML_MCP_USER_PASSWORD   set explicitly if you want to log in via the
                             web GUI as the MCP user; auto-generated &
                             printed to stderr on first run otherwise.
"""
from __future__ import annotations

import os
import re
import secrets
import sys
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from dungml import (
    DmapParseError,
    Diagnostic,
    DungeonMap,
    Graph,
    build_graph,
    door_key,
    fog_of_war,
    get_renderer,
    is_blocked,
    list_renderers,
    parse,
    validate as dsl_validate,
)
from dungml.geometry import corridor_polygons, room_polygon
from dungml_backend import auth, models
from dungml_backend.db import get_sessionmaker, init_schema

mcp = FastMCP("dungml")


# ----- MCP user bootstrap -----

_MCP_USER_EMAIL = os.environ.get("DUNGML_MCP_USER_EMAIL", "mcp@local")


def _get_or_create_mcp_user(db: DbSession) -> models.User:
    """Look up the MCP-owned user (by email); create it if absent.

    The password is taken from `DUNGML_MCP_USER_PASSWORD` if set;
    otherwise a fresh one is generated and printed to stderr (one time,
    on the first run that creates the row). The user can then log into
    the web GUI with these credentials to inspect what the MCP server
    has stored.
    """
    user = db.scalars(
        select(models.User).where(models.User.email == _MCP_USER_EMAIL)
    ).first()
    if user is not None:
        return user
    password = os.environ.get("DUNGML_MCP_USER_PASSWORD")
    generated = False
    if not password:
        password = secrets.token_urlsafe(18)
        generated = True
    user = models.User(
        email=_MCP_USER_EMAIL,
        password_hash=auth.hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if generated:
        sys.stderr.write(
            f"[dungml-mcp] Provisioned MCP user {_MCP_USER_EMAIL}\n"
            f"[dungml-mcp] Web-GUI password: {password}\n"
            f"[dungml-mcp] (Set DUNGML_MCP_USER_PASSWORD in env to override.)\n"
        )
        sys.stderr.flush()
    return user


# ----- DB session helper -----

def _session():
    """One-shot DB session wrapping a tool call. Caller is responsible for
    commit/rollback. The MCP server is request-response so we open a
    short-lived session per call to keep state simple and avoid stale
    rows across long-running clients."""
    return get_sessionmaker()()


def _owned_project(db: DbSession, project_id: str, user_id: str) -> models.Project:
    p = db.get(models.Project, project_id)
    if p is None or p.user_id != user_id:
        raise ValueError(f"project {project_id!r} not found")
    return p


def _owned_map(db: DbSession, map_id: str, user_id: str) -> models.Map:
    m = db.get(models.Map, map_id)
    if m is None:
        raise ValueError(f"map {map_id!r} not found")
    # Walk up to the owning user to confirm.
    project = db.get(models.Project, m.project_id)
    if project is None or project.user_id != user_id:
        raise ValueError(f"map {map_id!r} not found")
    return m


def _owned_session(db: DbSession, session_id: str, user_id: str) -> models.PlaySession:
    s = db.get(models.PlaySession, session_id)
    if s is None:
        raise ValueError(f"play-session {session_id!r} not found")
    # Walk up map -> project -> user to confirm ownership.
    _owned_map(db, s.map_id, user_id)
    return s


def _graph_for_session(s: models.PlaySession, db: DbSession) -> tuple[DungeonMap, Graph]:
    """Parse the session's map source and derive its connectivity graph."""
    m = db.get(models.Map, s.map_id)
    if m is None:
        raise ValueError(f"map {s.map_id!r} for session {s.id!r} not found")
    try:
        dmap = parse(m.source or "")
    except DmapParseError as e:
        raise ValueError(f"map source has a parse error: {e}") from e
    return dmap, build_graph(dmap)


def _effective_state(s: models.PlaySession, key: str, authored: str) -> str:
    """Runtime door state: a session override if present, else the authored one."""
    return (s.door_states or {}).get(key, authored)


def _reveal_node(g: Graph, node: str, nodes: set[str], doors: set[str]) -> None:
    """Mark `node` discovered and reveal its visible (non-concealed) doors.

    Concealed doors (secret/hidden) stay hidden until found explicitly via
    `mark_door` — seeing a room doesn't reveal its secret passages.
    """
    nodes.add(node)
    for edge in g.incident_edges(node):
        if not edge.hidden:
            doors.add(edge.key)
    for b in g.boundary_exits(node):
        if not b.hidden:
            doors.add(b.key)


def _session_dict(s: models.PlaySession) -> dict:
    return {
        "id": s.id,
        "map_id": s.map_id,
        "name": s.name,
        "party_location": s.party_location,
        "discovered_nodes": sorted(s.discovered_nodes or []),
        "discovered_doors": sorted(s.discovered_doors or []),
        "door_states": dict(s.door_states or {}),
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


# ----- structured-authoring helpers -----
#
# These let the model grow a map by describing geometry relative to what's
# already there ("a 8x6 room east of room.hall") instead of inventing
# coordinates. Placement maths runs here, server-side; the model never does
# spatial reasoning. We append well-formed `.dmap` snippets to the source
# (additive — existing text, comments and formatting are preserved) and
# re-validate before saving so a bad edit can't corrupt the map.

BBox = tuple[float, float, float, float]  # (x0, y0, x1, y1)


def _num(n: float) -> str:
    """Format a coordinate: 14.0 -> '14', 9.5 -> '9.5'."""
    i = int(n)
    return str(i) if float(n) == i else str(n)


def _node_objects(dmap: DungeonMap) -> dict[str, object]:
    """Map every node id ('room.x' / 'corridor.y') to its model object,
    across the top level and all layers."""
    out: dict[str, object] = {}
    for name, room in dmap.rooms.items():
        out[f"room.{name}"] = room
    for name, corr in dmap.corridors.items():
        out[f"corridor.{name}"] = corr
    for layer in dmap.layers:
        for room in layer.rooms:
            out[f"room.{room.name}"] = room
        for corr in layer.corridors:
            out[f"corridor.{corr.name}"] = corr
    return out


def _bbox_of(node_id: str, obj: object) -> BBox:
    if node_id.startswith("room."):
        pts = room_polygon(obj)  # type: ignore[arg-type]
    else:
        polys = corridor_polygons(obj)  # type: ignore[arg-type]
        pts = [p for poly in polys for p in poly]
    if not pts:
        raise ValueError(f"node {node_id!r} has no geometry to anchor against")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _center(b: BBox) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _facing_edge_point(a: BBox, b: BBox) -> tuple[float, float]:
    """A point on `a`'s boundary on the side that faces `b`."""
    acx, acy = _center(a)
    bcx, bcy = _center(b)
    dx, dy = bcx - acx, bcy - acy
    if abs(dx) >= abs(dy):  # horizontal relationship
        x = a[2] if dx >= 0 else a[0]
        lo, hi = max(a[1], b[1]), min(a[3], b[3])
        y = (lo + hi) / 2 if lo < hi else acy
        return (x, y)
    y = a[3] if dy >= 0 else a[1]
    lo, hi = max(a[0], b[0]), min(a[2], b[2])
    x = (lo + hi) / 2 if lo < hi else acx
    return (x, y)


def _between_point(a: BBox, b: BBox) -> tuple[float, float]:
    """A point on the boundary between two areas (midpoint of their facing
    edges) — where a connecting door naturally sits."""
    pa = _facing_edge_point(a, b)
    pb = _facing_edge_point(b, a)
    return ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)


def _place_rect(anchor: BBox, direction: str, w: float, h: float, gap: float,
                origin: str) -> BBox:
    """Position a `w`x`h` rect adjacent to `anchor` in a cardinal direction,
    centred on the shared edge, separated by `gap`. Honours grid origin so
    'north' is visually up either way."""
    acx, acy = _center(anchor)
    direction = direction.lower()
    # Screen-down is +y for a top-left origin; flipped for bottom-left.
    up_is_negative_y = origin != "bottom-left"
    if direction == "east":
        return (anchor[2] + gap, acy - h / 2, anchor[2] + gap + w, acy + h / 2)
    if direction == "west":
        return (anchor[0] - gap - w, acy - h / 2, anchor[0] - gap, acy + h / 2)
    if direction in ("north", "south"):
        up = direction == "north"
        # Going up means smaller y for a top-left origin.
        above = up if up_is_negative_y else (not up)
        if above:
            y1 = anchor[1] - gap
            y0 = y1 - h
        else:
            y0 = anchor[3] + gap
            y1 = y0 + h
        return (acx - w / 2, y0, acx + w / 2, y1)
    raise ValueError(f"direction must be north/south/east/west, got {direction!r}")


def _grow_bounds(source: str, need_x: float, need_y: float, margin: float = 2.0) -> str:
    """Enlarge the map's `grid bounds` so new geometry fits (never shrinks)."""
    m = re.search(r"bounds\s+([\d.]+)\s*x\s*([\d.]+)", source)
    if not m:
        return source
    w, h = float(m.group(1)), float(m.group(2))
    nw, nh = max(w, need_x + margin), max(h, need_y + margin)
    if nw == w and nh == h:
        return source
    return source[: m.start()] + f"bounds {_num(nw)} x {_num(nh)}" + source[m.end():]


def _emit_room(name: str, b: BBox, label: str | None, description: str | None) -> str:
    w, h = b[2] - b[0], b[3] - b[1]
    lines = [f'room "{name}" {{', f"  rect {_num(b[0])},{_num(b[1])} {_num(w)} x {_num(h)}"]
    if label:
        lines.append(f'  label "{label}"')
    if description:
        lines.append(f'  description "{description}"')
    lines.append("}")
    return "\n" + "\n".join(lines) + "\n"


def _emit_corridor(name: str, start: tuple[float, float],
                   end: tuple[float, float], width: float) -> str:
    return (
        f'\ncorridor "{name}" {{\n'
        f"  width {_num(width)}\n"
        f"  segment line from {_num(start[0])},{_num(start[1])} "
        f"to {_num(end[0])},{_num(end[1])}\n"
        f"}}\n"
    )


def _emit_door(pos: tuple[float, float], refs: list[str], dtype: str,
               state: str, facing: str | None, description: str | None) -> str:
    lines = [f"door at {_num(pos[0])},{_num(pos[1])} {{",
             f"  connects {', '.join(refs)}"]
    if dtype and dtype != "wooden":
        lines.append(f"  type {dtype}")
    if state and state != "closed":
        lines.append(f"  state {state}")
    if facing:
        lines.append(f"  facing {facing}")
    if description:
        lines.append(f'  description "{description}"')
    lines.append("}")
    return "\n" + "\n".join(lines) + "\n"


def _commit_source(db: DbSession, m: models.Map, new_source: str) -> list[dict]:
    """Validate `new_source`; on any error diagnostic, raise without saving.
    Returns the (warning-level) diagnostics on success."""
    try:
        dmap = parse(new_source)
    except DmapParseError as e:
        raise ValueError(f"edit would break the map (parse error): {e}") from e
    diags = [_diag_to_dict(d) for d in dsl_validate(dmap)]
    errors = [d for d in diags if d["severity"] == "error"]
    if errors:
        msg = "; ".join(d["message"] for d in errors[:3])
        raise ValueError(f"edit would introduce validation errors: {msg}")
    m.source = new_source
    db.commit()
    return diags


def _discover_in_session(db: DbSession, user_id: str, session_id: str,
                         nodes: list[str], doors: list[str]) -> None:
    """Mark freshly-authored geometry as discovered in a play-session, so a
    'party as cartographer' flow reveals what it just built."""
    s = _owned_session(db, session_id, user_id)
    nset = set(s.discovered_nodes or []) | set(nodes)
    dset = set(s.discovered_doors or []) | set(doors)
    s.discovered_nodes = sorted(nset)
    s.discovered_doors = sorted(dset)
    db.commit()


def _diag_to_dict(d: Diagnostic) -> dict:
    return {
        "severity": d.severity,
        "message": d.message,
        "line": d.line,
        "column": d.column,
        "end_line": d.end_line,
        "end_column": d.end_column,
    }


# ----- tools -----

@mcp.tool()
def list_projects() -> list[dict]:
    """List all projects owned by the MCP user, newest first."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        rows = db.scalars(
            select(models.Project)
            .where(models.Project.user_id == user.id)
            .order_by(models.Project.updated_at.desc())
        ).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "created_at": p.created_at.isoformat(),
                "updated_at": p.updated_at.isoformat(),
            }
            for p in rows
        ]


@mcp.tool()
def create_project(
    name: Annotated[str, Field(description="Display name for the project.")],
) -> dict:
    """Create a new (empty) project. Returns the new project's id + name."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        proj = models.Project(user_id=user.id, name=name)
        db.add(proj)
        db.commit()
        db.refresh(proj)
        return {"id": proj.id, "name": proj.name}


@mcp.tool()
def delete_project(
    project_id: Annotated[str, Field(description="Project UUID to delete.")],
) -> dict:
    """Delete a project and every map inside it. Returns {ok: true}."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        proj = _owned_project(db, project_id, user.id)
        db.delete(proj)
        db.commit()
        return {"ok": True, "deleted": project_id}


@mcp.tool()
def list_maps(
    project_id: Annotated[str, Field(description="Project UUID.")],
) -> list[dict]:
    """List every map in a project. Returns summaries (no source text)."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        proj = _owned_project(db, project_id, user.id)
        rows = db.scalars(
            select(models.Map)
            .where(models.Map.project_id == proj.id)
            .order_by(models.Map.updated_at.desc())
        ).all()
        return [
            {
                "id": m.id,
                "project_id": m.project_id,
                "name": m.name,
                "kind": m.kind,
                "created_at": m.created_at.isoformat(),
                "updated_at": m.updated_at.isoformat(),
            }
            for m in rows
        ]


@mcp.tool()
def create_map(
    project_id: Annotated[str, Field(description="Project UUID to add the map to.")],
    name: Annotated[str, Field(description="Map display name.")],
    source: Annotated[
        str,
        Field(
            default="",
            description="Initial .dmap source. Defaults to empty string.",
        ),
    ] = "",
) -> dict:
    """Create a new map inside an existing project. Returns the new map id."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        proj = _owned_project(db, project_id, user.id)
        m = models.Map(project_id=proj.id, name=name, source=source)
        db.add(m)
        db.commit()
        db.refresh(m)
        return {"id": m.id, "project_id": m.project_id, "name": m.name, "kind": m.kind}


@mcp.tool()
def get_map(
    map_id: Annotated[str, Field(description="Map UUID.")],
) -> dict:
    """Fetch the full stored source for a map."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        m = _owned_map(db, map_id, user.id)
        return {
            "id": m.id,
            "project_id": m.project_id,
            "name": m.name,
            "kind": m.kind,
            "source": m.source,
            "created_at": m.created_at.isoformat(),
            "updated_at": m.updated_at.isoformat(),
        }


@mcp.tool()
def update_map(
    map_id: Annotated[str, Field(description="Map UUID to update.")],
    name: Annotated[
        str | None,
        Field(default=None, description="New display name. Leave unset to keep."),
    ] = None,
    source: Annotated[
        str | None,
        Field(default=None, description="New .dmap source. Leave unset to keep."),
    ] = None,
) -> dict:
    """Patch a map's name and/or source. At least one must be provided."""
    if name is None and source is None:
        raise ValueError("update_map requires at least one of `name`, `source`")
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        m = _owned_map(db, map_id, user.id)
        if name is not None:
            m.name = name
        if source is not None:
            m.source = source
        db.commit()
        db.refresh(m)
        return {"id": m.id, "name": m.name, "kind": m.kind}


@mcp.tool()
def delete_map(
    map_id: Annotated[str, Field(description="Map UUID to delete.")],
) -> dict:
    """Delete a single map."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        m = _owned_map(db, map_id, user.id)
        db.delete(m)
        db.commit()
        return {"ok": True, "deleted": map_id}


@mcp.tool()
def render_map(
    map_id: Annotated[
        str | None,
        Field(default=None, description="Stored map UUID to render."),
    ] = None,
    source: Annotated[
        str | None,
        Field(default=None, description="Inline .dmap source to render (overrides map_id)."),
    ] = None,
    renderer: Annotated[
        str | None,
        Field(default=None, description="Renderer name override (e.g. 'hatched')."),
    ] = None,
) -> dict:
    """Render a map to SVG. Provide exactly one of `map_id` or `source`.

    Returns {svg: "<svg ...>...</svg>", diagnostics: [...]}.
    Parse errors raise; lower-severity diagnostics are returned alongside
    the SVG so non-fatal warnings don't block rendering.
    """
    if (map_id is None) == (source is None):
        raise ValueError("render_map: provide exactly one of `map_id`, `source`")
    if map_id is not None:
        with _session() as db:
            user = _get_or_create_mcp_user(db)
            m = _owned_map(db, map_id, user.id)
            src = m.source
    else:
        src = source or ""
    try:
        dmap = parse(src)
    except DmapParseError as e:
        raise ValueError(f"parse error: {e}") from e
    diagnostics = [_diag_to_dict(d) for d in dsl_validate(dmap)]
    name = renderer or dmap.map.renderer
    try:
        svg = get_renderer(name)().render(dmap)
    except KeyError as e:
        raise ValueError(f"unknown renderer: {e}") from e
    return {"svg": svg, "diagnostics": diagnostics}


@mcp.tool()
def validate_source(
    source: Annotated[str, Field(description=".dmap source to validate.")],
) -> dict:
    """Parse + validate a .dmap source. Returns {ok, diagnostics, error?}."""
    try:
        dmap = parse(source)
    except DmapParseError as e:
        return {
            "ok": False,
            "diagnostics": [],
            "error": {
                "message": str(e),
                "line": getattr(e, "line", 0) or 0,
                "column": getattr(e, "column", 0) or 0,
            },
        }
    diagnostics = [_diag_to_dict(d) for d in dsl_validate(dmap)]
    has_error = any(d["severity"] == "error" for d in diagnostics)
    return {"ok": not has_error, "diagnostics": diagnostics}


@mcp.tool()
def list_renderer_names() -> list[str]:
    """List the renderer names recognised by the `renderer` map property
    (e.g. "classic-bw", "floorplan", "hatched")."""
    return sorted(list_renderers())


# ----- structured-authoring tools (grow a map as you go) -----

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_name(name: str, kind: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(
            f"{kind} name {name!r} must be a bare identifier "
            f"(letters, digits, underscores; no spaces) so doors can reference it"
        )


def _door_key_pos(pos: tuple[float, float]) -> str:
    return f"{_num(pos[0])},{_num(pos[1])}"


@mcp.tool()
def add_room(
    map_id: Annotated[str, Field(description="Map UUID to add the room to.")],
    name: Annotated[
        str, Field(description="New room id (bare identifier, e.g. 'guard_post').")
    ],
    width: Annotated[float, Field(description="Room width in world units.")],
    height: Annotated[float, Field(description="Room height in world units.")],
    direction: Annotated[
        str | None,
        Field(
            default=None,
            description="Place relative to `anchor`: 'north' | 'south' | 'east' | "
            "'west'. Required unless `position` is given.",
        ),
    ] = None,
    anchor: Annotated[
        str | None,
        Field(
            default=None,
            description="Existing node to place against, e.g. 'room.hall'. "
            "Required with `direction`.",
        ),
    ] = None,
    position: Annotated[
        str | None,
        Field(
            default=None,
            description="Explicit top-left corner 'x,y' instead of anchor/direction "
            "(use for the very first room).",
        ),
    ] = None,
    gap: Annotated[
        float,
        Field(
            default=0.0,
            description="Space between anchor and new room. 0 = share a wall (single "
            "connecting door); >0 = separated, joined by a short corridor.",
        ),
    ] = 0.0,
    label: Annotated[str | None, Field(default=None, description="On-map label.")] = None,
    description: Annotated[
        str | None, Field(default=None, description="Read-aloud room description.")
    ] = None,
    connect: Annotated[
        bool,
        Field(default=True, description="Auto-add a door (and corridor if gap>0) to the anchor."),
    ] = True,
    door_type: Annotated[str, Field(default="wooden", description="Connecting door type.")] = "wooden",
    door_state: Annotated[str, Field(default="closed", description="Connecting door state.")] = "closed",
    discover_in_session: Annotated[
        str | None,
        Field(default=None, description="If set, mark the new geometry discovered in this play-session."),
    ] = None,
) -> dict:
    """Add a room positioned relative to an existing one — the placement
    maths runs server-side, so describe *where* ('east of room.hall'),
    not raw coordinates. Optionally auto-connects it with a door/corridor.
    Re-validates before saving; nothing is written if the edit is invalid.
    """
    _check_name(name, "room")
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        m = _owned_map(db, map_id, user.id)
        try:
            dmap = parse(m.source or "")
        except DmapParseError as e:
            raise ValueError(f"current map source has a parse error: {e}") from e
        nodes = _node_objects(dmap)
        if f"room.{name}" in nodes:
            raise ValueError(f"a room named {name!r} already exists")

        anchor_bbox = None
        if position is not None:
            try:
                px, py = (float(v) for v in position.split(","))
            except ValueError:
                raise ValueError("position must be 'x,y'")
            b = (px, py, px + width, py + height)
        elif anchor is not None and direction is not None:
            if anchor not in nodes:
                raise ValueError(f"unknown anchor node {anchor!r}")
            anchor_bbox = _bbox_of(anchor, nodes[anchor])
            b = _place_rect(anchor_bbox, direction, width, height, gap,
                            dmap.map.grid.origin)
        else:
            raise ValueError("provide either `position` or both `anchor` and `direction`")

        new_nodes = [f"room.{name}"]
        new_doors: list[str] = []
        max_x = b[2]
        max_y = b[3]
        snippet = _emit_room(name, b, label, description)

        if connect and anchor is not None:
            anchor_bbox = anchor_bbox or _bbox_of(anchor, nodes[anchor])
            if gap <= 0:
                pos = _between_point(anchor_bbox, b)
                snippet += _emit_door(pos, [anchor, f"room.{name}"], door_type,
                                      door_state, None, None)
                new_doors.append(_door_key_pos(pos))
                max_x, max_y = max(max_x, pos[0]), max(max_y, pos[1])
            else:
                cname = f"{anchor.split('.', 1)[1]}_to_{name}"
                _check_name(cname, "corridor")
                if f"corridor.{cname}" in nodes:
                    raise ValueError(f"a corridor named {cname!r} already exists")
                start = _facing_edge_point(anchor_bbox, b)
                end = _facing_edge_point(b, anchor_bbox)
                snippet += _emit_corridor(cname, start, end, max(1.0, min(width, height) / 2))
                snippet += _emit_door(start, [anchor, f"corridor.{cname}"], door_type,
                                      door_state, None, None)
                snippet += _emit_door(end, [f"room.{name}", f"corridor.{cname}"],
                                      door_type, door_state, None, None)
                new_nodes.append(f"corridor.{cname}")
                new_doors += [_door_key_pos(start), _door_key_pos(end)]
                max_x = max(max_x, start[0], end[0])
                max_y = max(max_y, start[1], end[1])

        if b[0] < 0 or b[1] < 0:
            raise ValueError(
                "placement extends past the map origin (negative coordinates); "
                "start the first room with more headroom, or build east/south"
            )

        new_source = _grow_bounds(m.source or "", max_x, max_y) + snippet
        diags = _commit_source(db, m, new_source)
        if discover_in_session:
            _discover_in_session(db, user.id, discover_in_session, new_nodes, new_doors)
        return {
            "node": f"room.{name}",
            "bbox": list(b),
            "new_nodes": new_nodes,
            "new_doors": new_doors,
            "diagnostics": diags,
        }


@mcp.tool()
def add_corridor(
    map_id: Annotated[str, Field(description="Map UUID.")],
    name: Annotated[str, Field(description="New corridor id (bare identifier).")],
    from_node: Annotated[str, Field(description="Node to start at, e.g. 'room.hall'.")],
    to_node: Annotated[str, Field(description="Node to end at, e.g. 'room.vault'.")],
    width: Annotated[float, Field(default=2.0, description="Corridor width.")] = 2.0,
    connect: Annotated[
        bool,
        Field(default=True, description="Add doors at both ends linking the corridor to each node."),
    ] = True,
    door_type: Annotated[str, Field(default="wooden", description="End-door type.")] = "wooden",
    door_state: Annotated[str, Field(default="closed", description="End-door state.")] = "closed",
    discover_in_session: Annotated[
        str | None,
        Field(default=None, description="If set, mark the new geometry discovered in this play-session."),
    ] = None,
) -> dict:
    """Join two existing rooms/corridors with a straight corridor. Endpoints
    are computed from each node's geometry; doors are added at both ends so
    the connection is routable. Re-validates before saving."""
    _check_name(name, "corridor")
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        m = _owned_map(db, map_id, user.id)
        try:
            dmap = parse(m.source or "")
        except DmapParseError as e:
            raise ValueError(f"current map source has a parse error: {e}") from e
        nodes = _node_objects(dmap)
        if f"corridor.{name}" in nodes:
            raise ValueError(f"a corridor named {name!r} already exists")
        for n in (from_node, to_node):
            if n not in nodes:
                raise ValueError(f"unknown node {n!r}")
        a_bbox = _bbox_of(from_node, nodes[from_node])
        b_bbox = _bbox_of(to_node, nodes[to_node])
        start = _facing_edge_point(a_bbox, b_bbox)
        end = _facing_edge_point(b_bbox, a_bbox)
        snippet = _emit_corridor(name, start, end, width)
        new_doors: list[str] = []
        if connect:
            snippet += _emit_door(start, [from_node, f"corridor.{name}"], door_type,
                                  door_state, None, None)
            snippet += _emit_door(end, [to_node, f"corridor.{name}"], door_type,
                                  door_state, None, None)
            new_doors = [_door_key_pos(start), _door_key_pos(end)]
        new_source = _grow_bounds(
            m.source or "", max(start[0], end[0]), max(start[1], end[1])
        ) + snippet
        diags = _commit_source(db, m, new_source)
        if discover_in_session:
            _discover_in_session(
                db, user.id, discover_in_session, [f"corridor.{name}"], new_doors
            )
        return {
            "node": f"corridor.{name}",
            "from": list(start),
            "to": list(end),
            "new_doors": new_doors,
            "diagnostics": diags,
        }


@mcp.tool()
def add_door(
    map_id: Annotated[str, Field(description="Map UUID.")],
    between: Annotated[
        list[str] | None,
        Field(
            default=None,
            description="Two node ids to connect, e.g. ['room.hall','room.vault']. "
            "The door position is computed from their geometry.",
        ),
    ] = None,
    connects: Annotated[
        list[str] | None,
        Field(
            default=None,
            description="Explicit connects refs (use with `position`). One ref = a "
            "boundary/secret door to outside.",
        ),
    ] = None,
    position: Annotated[
        str | None,
        Field(default=None, description="Explicit 'x,y'. Required if `between` is not given."),
    ] = None,
    type: Annotated[str, Field(default="wooden", description="Door type (e.g. 'iron','secret').")] = "wooden",
    state: Annotated[str, Field(default="closed", description="Door state (e.g. 'locked').")] = "closed",
    facing: Annotated[str | None, Field(default=None, description="Optional facing direction.")] = None,
    description: Annotated[str | None, Field(default=None, description="Door description.")] = None,
    discover_in_session: Annotated[
        str | None,
        Field(default=None, description="If set, mark the door discovered in this play-session."),
    ] = None,
) -> dict:
    """Add a door between two existing nodes (position auto-computed) or at
    an explicit position. Use this for extra connections, locked doors, or
    secret doors the party might later find. Re-validates before saving."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        m = _owned_map(db, map_id, user.id)
        try:
            dmap = parse(m.source or "")
        except DmapParseError as e:
            raise ValueError(f"current map source has a parse error: {e}") from e
        nodes = _node_objects(dmap)
        if between is not None:
            if len(between) != 2:
                raise ValueError("`between` must list exactly two node ids")
            for n in between:
                if n not in nodes:
                    raise ValueError(f"unknown node {n!r}")
            pos = _between_point(_bbox_of(between[0], nodes[between[0]]),
                                 _bbox_of(between[1], nodes[between[1]]))
            refs = list(between)
        elif position is not None and connects:
            try:
                px, py = (float(v) for v in position.split(","))
            except ValueError:
                raise ValueError("position must be 'x,y'")
            pos = (px, py)
            for r in connects:
                if r not in nodes:
                    raise ValueError(f"unknown node {r!r}")
            refs = list(connects)
        else:
            raise ValueError("provide `between`, or both `position` and `connects`")

        snippet = _emit_door(pos, refs, type, state, facing, description)
        new_source = _grow_bounds(m.source or "", pos[0], pos[1]) + snippet
        diags = _commit_source(db, m, new_source)
        key = _door_key_pos(pos)
        if discover_in_session:
            _discover_in_session(db, user.id, discover_in_session, [], [key])
        return {"door": key, "position": list(pos), "connects": refs, "diagnostics": diags}


# ----- play-session tools (exploration / fog-of-war / pathfinding) -----
#
# A play-session is a runtime overlay on a map: which rooms/corridors the
# party has discovered, which doors they've found, the live state of those
# doors, and where the party is. The map's `.dmap` source stays immutable;
# the connectivity graph (rooms + corridors as nodes, doors as edges) is
# re-derived from it on demand. Two pathfinding modes:
#   - "discovered": only nodes seen + doors found and currently passable
#                   (a locked door blocks until you `mark_door ... state open`)
#   - "any":        the full authored topology, ignoring discovery and locks
#                   (the DM question "does a route exist at all?")


@mcp.tool()
def create_session(
    map_id: Annotated[str, Field(description="Map UUID this play-through is on.")],
    name: Annotated[str, Field(description="Session display name (e.g. party / date).")],
    start_location: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional starting node ('room.NAME' or 'corridor.NAME'); "
            "marked discovered and set as the party location.",
        ),
    ] = None,
) -> dict:
    """Start a new play-session for a map. Returns the session state."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        m = _owned_map(db, map_id, user.id)
        nodes: set[str] = set()
        doors: set[str] = set()
        party = None
        if start_location is not None:
            try:
                g = build_graph(parse(m.source or ""))
            except DmapParseError as e:
                raise ValueError(f"map source has a parse error: {e}") from e
            if not g.has_node(start_location):
                raise ValueError(f"unknown node {start_location!r} in map")
            _reveal_node(g, start_location, nodes, doors)
            party = start_location
        s = models.PlaySession(
            map_id=m.id,
            name=name,
            party_location=party,
            discovered_nodes=sorted(nodes),
            discovered_doors=sorted(doors),
            door_states={},
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return _session_dict(s)


@mcp.tool()
def list_sessions(
    map_id: Annotated[str, Field(description="Map UUID.")],
) -> list[dict]:
    """List every play-session on a map, newest first."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        m = _owned_map(db, map_id, user.id)
        rows = db.scalars(
            select(models.PlaySession)
            .where(models.PlaySession.map_id == m.id)
            .order_by(models.PlaySession.updated_at.desc())
        ).all()
        return [_session_dict(s) for s in rows]


@mcp.tool()
def get_session(
    session_id: Annotated[str, Field(description="Play-session UUID.")],
) -> dict:
    """Fetch a play-session's full discovery + door state."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        s = _owned_session(db, session_id, user.id)
        return _session_dict(s)


@mcp.tool()
def delete_session(
    session_id: Annotated[str, Field(description="Play-session UUID to delete.")],
) -> dict:
    """Delete a play-session. The underlying map is untouched."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        s = _owned_session(db, session_id, user.id)
        db.delete(s)
        db.commit()
        return {"ok": True, "deleted": session_id}


@mcp.tool()
def set_party_location(
    session_id: Annotated[str, Field(description="Play-session UUID.")],
    location: Annotated[
        str, Field(description="Node id: 'room.NAME' or 'corridor.NAME'.")
    ],
) -> dict:
    """Move the party to a node. The node is marked discovered (and its
    visible doors revealed) as a side effect."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        s = _owned_session(db, session_id, user.id)
        _dmap, g = _graph_for_session(s, db)
        if not g.has_node(location):
            raise ValueError(f"unknown node {location!r} in map")
        nodes = set(s.discovered_nodes or [])
        doors = set(s.discovered_doors or [])
        _reveal_node(g, location, nodes, doors)
        s.party_location = location
        s.discovered_nodes = sorted(nodes)
        s.discovered_doors = sorted(doors)
        db.commit()
        db.refresh(s)
        return _session_dict(s)


@mcp.tool()
def mark_discovered(
    session_id: Annotated[str, Field(description="Play-session UUID.")],
    node: Annotated[
        str, Field(description="Node id to reveal: 'room.NAME' or 'corridor.NAME'.")
    ],
    reveal_doors: Annotated[
        bool,
        Field(
            default=True,
            description="Also reveal the node's visible (non-secret) doors.",
        ),
    ] = True,
) -> dict:
    """Mark a room or corridor as discovered by the party."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        s = _owned_session(db, session_id, user.id)
        _dmap, g = _graph_for_session(s, db)
        if not g.has_node(node):
            raise ValueError(f"unknown node {node!r} in map")
        nodes = set(s.discovered_nodes or [])
        doors = set(s.discovered_doors or [])
        if reveal_doors:
            _reveal_node(g, node, nodes, doors)
        else:
            nodes.add(node)
        s.discovered_nodes = sorted(nodes)
        s.discovered_doors = sorted(doors)
        db.commit()
        db.refresh(s)
        return _session_dict(s)


@mcp.tool()
def mark_door(
    session_id: Annotated[str, Field(description="Play-session UUID.")],
    door: Annotated[
        str,
        Field(description="Door key (its 'x,y' position, as returned by get_exits)."),
    ],
    discovered: Annotated[
        bool,
        Field(default=True, description="Mark the door as found (e.g. a secret door)."),
    ] = True,
    state: Annotated[
        str | None,
        Field(
            default=None,
            description="Runtime state override: 'open', 'closed', 'locked', "
            "'unlocked', etc. Leave unset to keep the authored state.",
        ),
    ] = None,
) -> dict:
    """Discover a door and/or change its runtime state (open/unlock/lock).

    Use this when the party finds a secret door, or opens/unlocks/bars an
    existing one — it's what makes a previously blocked edge passable."""
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        s = _owned_session(db, session_id, user.id)
        _dmap, g = _graph_for_session(s, db)
        known = {e.key for e in g.edges} | {b.key for b in g.boundary}
        if door not in known:
            raise ValueError(f"unknown door {door!r} in map")
        doors = set(s.discovered_doors or [])
        if discovered:
            doors.add(door)
        s.discovered_doors = sorted(doors)
        if state is not None:
            states = dict(s.door_states or {})
            states[door] = state
            s.door_states = states
        db.commit()
        db.refresh(s)
        return _session_dict(s)


@mcp.tool()
def get_exits(
    session_id: Annotated[str, Field(description="Play-session UUID.")],
    node: Annotated[
        str, Field(description="Node id: 'room.NAME' or 'corridor.NAME'.")
    ],
    mode: Annotated[
        str,
        Field(
            default="discovered",
            description="'discovered' = only doors the party has found; "
            "'any' = every exit in the authored map.",
        ),
    ] = "discovered",
) -> dict:
    """List the exits from a room/corridor — the answer to
    'what are the ways out of here?'

    Each exit reports the door key, the node it leads to (null = an opening
    to outside the mapped area), the door type and current state, whether
    it's been discovered, whether it's passable right now, and whether the
    far side has been explored yet.
    """
    if mode not in ("discovered", "any"):
        raise ValueError("mode must be 'discovered' or 'any'")
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        s = _owned_session(db, session_id, user.id)
        _dmap, g = _graph_for_session(s, db)
        if not g.has_node(node):
            raise ValueError(f"unknown node {node!r} in map")
        discovered_doors = set(s.discovered_doors or [])
        discovered_nodes = set(s.discovered_nodes or [])
        exits: list[dict] = []
        for edge in g.incident_edges(node):
            found = edge.key in discovered_doors
            if mode == "discovered" and not found:
                continue
            state = _effective_state(s, edge.key, edge.state)
            other = edge.other(node)
            exits.append(
                {
                    "door": edge.key,
                    "to": other,
                    "type": edge.type,
                    "state": state,
                    "discovered": found,
                    "passable_now": found and not is_blocked(state),
                    "far_side_explored": other in discovered_nodes,
                }
            )
        for b in g.boundary_exits(node):
            found = b.key in discovered_doors
            if mode == "discovered" and not found:
                continue
            state = _effective_state(s, b.key, b.state)
            exits.append(
                {
                    "door": b.key,
                    "to": None,  # leads outside the mapped area
                    "type": b.type,
                    "state": state,
                    "discovered": found,
                    "passable_now": found and not is_blocked(state),
                    "far_side_explored": False,
                }
            )
        return {"node": node, "mode": mode, "exits": exits}


@mcp.tool()
def find_path(
    session_id: Annotated[str, Field(description="Play-session UUID.")],
    from_node: Annotated[str, Field(description="Start node id.")],
    to_node: Annotated[str, Field(description="Destination node id.")],
    mode: Annotated[
        str,
        Field(
            default="discovered",
            description="'discovered' = route over explored nodes and found, "
            "currently-passable doors only; 'any' = the full authored "
            "topology, ignoring discovery and locked doors.",
        ),
    ] = "discovered",
) -> dict:
    """Find the shortest route between two nodes. Pathfinding runs
    server-side (BFS) so the model never reconstructs the map itself.

    Returns {found, nodes, doors, steps, length} or {found: false}.
    """
    if mode not in ("discovered", "any"):
        raise ValueError("mode must be 'discovered' or 'any'")
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        s = _owned_session(db, session_id, user.id)
        _dmap, g = _graph_for_session(s, db)
        if not g.has_node(from_node):
            raise ValueError(f"unknown node {from_node!r} in map")
        if not g.has_node(to_node):
            raise ValueError(f"unknown node {to_node!r} in map")
        if mode == "discovered":
            discovered_doors = set(s.discovered_doors or [])
            discovered_nodes = set(s.discovered_nodes or [])

            def passable(e):
                return e.key in discovered_doors and not is_blocked(
                    _effective_state(s, e.key, e.state)
                )

            def node_ok(n):
                return n in discovered_nodes

            path = g.find_path(from_node, to_node, passable=passable, node_ok=node_ok)
        else:
            path = g.find_path(from_node, to_node)
        if path is None:
            return {"found": False, "from": from_node, "to": to_node, "mode": mode}
        result = path.to_dict()
        result["mode"] = mode
        return result


@mcp.tool()
def get_known_map(
    session_id: Annotated[str, Field(description="Play-session UUID.")],
) -> dict:
    """Return only the part of the map the party has discovered — the
    localized context to feed the model instead of the whole dungeon.

    Includes discovered nodes, the connections between them, the party
    location, and the 'frontier': discovered doors that lead somewhere not
    yet explored (where exploration can continue).
    """
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        s = _owned_session(db, session_id, user.id)
        _dmap, g = _graph_for_session(s, db)
        discovered_nodes = set(s.discovered_nodes or [])
        discovered_doors = set(s.discovered_doors or [])

        nodes = [
            {"id": nid, "kind": g.nodes[nid].kind, "name": g.nodes[nid].name}
            for nid in sorted(discovered_nodes)
            if nid in g.nodes
        ]
        connections: list[dict] = []
        frontier: list[dict] = []
        seen_edges: set[str] = set()
        for nid in discovered_nodes:
            for edge in g.incident_edges(nid):
                if edge.key not in discovered_doors or edge.key in seen_edges:
                    continue
                seen_edges.add(edge.key)
                state = _effective_state(s, edge.key, edge.state)
                a_seen = edge.a in discovered_nodes
                b_seen = edge.b in discovered_nodes
                if a_seen and b_seen:
                    connections.append(
                        {
                            "door": edge.key,
                            "between": [edge.a, edge.b],
                            "type": edge.type,
                            "state": state,
                        }
                    )
                else:
                    known, unknown = (edge.a, edge.b) if a_seen else (edge.b, edge.a)
                    frontier.append(
                        {
                            "door": edge.key,
                            "from": known,
                            "leads_to": unknown,
                            "type": edge.type,
                            "state": state,
                        }
                    )
        return {
            "party_location": s.party_location,
            "nodes": nodes,
            "connections": connections,
            "frontier": frontier,
        }


@mcp.tool()
def render_session(
    session_id: Annotated[str, Field(description="Play-session UUID.")],
    mode: Annotated[
        str,
        Field(
            default="discovered",
            description="'discovered' = fog-of-war (only explored areas); "
            "'full' = the whole authored map.",
        ),
    ] = "discovered",
    renderer: Annotated[
        str | None,
        Field(default=None, description="Renderer name override (e.g. 'hatched')."),
    ] = None,
) -> dict:
    """Render the map as the party currently knows it (fog-of-war) or in
    full. Returns {svg, diagnostics}."""
    if mode not in ("discovered", "full"):
        raise ValueError("mode must be 'discovered' or 'full'")
    with _session() as db:
        user = _get_or_create_mcp_user(db)
        s = _owned_session(db, session_id, user.id)
        dmap, _g = _graph_for_session(s, db)
        if mode == "discovered":
            dmap = fog_of_war(
                dmap,
                discovered_nodes=set(s.discovered_nodes or []),
                discovered_doors=set(s.discovered_doors or []),
            )
        diagnostics = [_diag_to_dict(d) for d in dsl_validate(dmap)]
        name = renderer or dmap.map.renderer
        try:
            svg = get_renderer(name)().render(dmap)
        except KeyError as e:
            raise ValueError(f"unknown renderer: {e}") from e
        return {"svg": svg, "diagnostics": diagnostics}


def run() -> None:
    """Entry point for the `dmap-mcp` console script.

    Initialises the DB schema (idempotent — matches what dmap-server does
    on startup) and runs the MCP server over stdio, the standard transport
    for desktop MCP clients like Claude Desktop.
    """
    init_schema()
    mcp.run()


if __name__ == "__main__":
    run()
