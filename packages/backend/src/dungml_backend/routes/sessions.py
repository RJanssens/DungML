"""Play sessions — fog-of-war exploration overlay on a stored map.

The map's `.dmap` source is authored truth; a session records only what a
party has discovered and where it stands. The connectivity graph is derived
from the source on demand (`dungml.graph`), and fog-of-war rendering reuses
`dungml.render_fogged`.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from dungml import (
    build_graph,
    is_blocked,
    parse,
    render_fogged,
    visible_doors,
)
from dungml.errors import DmapParseError

from .. import models
from ..deps import CurrentUser, DbDep

router = APIRouter(tags=["sessions"])


# ---- request bodies ----

class SessionCreateIn(BaseModel):
    name: str
    start_location: str | None = None


class MoveIn(BaseModel):
    to: str


class RevealIn(BaseModel):
    node: str
    reveal_doors: bool = True


# ---- helpers ----

def _get_owned_map(db, map_id: str, user: models.User) -> models.Map:
    m = db.get(models.Map, map_id)
    if m is None or m.project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "map not found")
    return m


def _get_owned_session(db, session_id: str, user: models.User) -> models.PlaySession:
    s = db.get(models.PlaySession, session_id)
    if s is None or s.map.project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return s


def _graph_for(m: models.Map):
    try:
        dmap = parse(m.source)
    except DmapParseError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"map does not parse: {e}"
        )
    return dmap, build_graph(dmap)


def _reveal(graph, node: str, nodes: set[str], doors: set[str]) -> None:
    """Mark `node` discovered and reveal the doors a party there can see."""
    nodes.add(node)
    doors |= visible_doors(graph, node)


def _exits(graph, node: str | None, discovered: set[str]) -> list[dict]:
    """Visible passages out of `node`: the neighbour, door key/state, and
    whether the neighbour has been explored yet (the move targets)."""
    if node is None or not graph.has_node(node):
        return []
    out: list[dict] = []
    for neighbor, edge in graph.neighbors(node):
        if edge.hidden:
            continue  # secret door — not an offered exit until revealed
        out.append(
            {
                "to": neighbor,
                "name": neighbor.split(".", 1)[-1],
                "door": edge.key,
                "type": edge.type,
                "state": edge.state,
                "blocked": is_blocked(edge.state),
                "discovered": neighbor in discovered,
            }
        )
    return out


def _serialize(s: models.PlaySession, graph) -> dict:
    discovered = set(s.discovered_nodes or [])
    return {
        "id": s.id,
        "map_id": s.map_id,
        "name": s.name,
        "party_location": s.party_location,
        "discovered_nodes": sorted(discovered),
        "discovered_doors": sorted(set(s.discovered_doors or [])),
        "exits": _exits(graph, s.party_location, discovered),
    }


# ---- routes ----

@router.post("/maps/{map_id}/sessions", status_code=status.HTTP_201_CREATED)
def create_session(map_id: str, body: SessionCreateIn, user: CurrentUser, db: DbDep):
    m = _get_owned_map(db, map_id, user)
    _, graph = _graph_for(m)
    nodes: set[str] = set()
    doors: set[str] = set()
    start = body.start_location
    if start:
        if not graph.has_node(start):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"unknown start location '{start}'"
            )
        _reveal(graph, start, nodes, doors)
    s = models.PlaySession(
        map_id=m.id,
        name=body.name,
        party_location=start,
        discovered_nodes=sorted(nodes),
        discovered_doors=sorted(doors),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _serialize(s, graph)


@router.get("/maps/{map_id}/sessions")
def list_sessions(map_id: str, user: CurrentUser, db: DbDep):
    m = _get_owned_map(db, map_id, user)
    _, graph = _graph_for(m)
    rows = sorted(m.play_sessions, key=lambda s: s.created_at, reverse=True)
    return [_serialize(s, graph) for s in rows]


@router.get("/sessions/{session_id}")
def get_session(session_id: str, user: CurrentUser, db: DbDep):
    s = _get_owned_session(db, session_id, user)
    _, graph = _graph_for(s.map)
    return _serialize(s, graph)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, user: CurrentUser, db: DbDep):
    s = _get_owned_session(db, session_id, user)
    db.delete(s)
    db.commit()


@router.post("/sessions/{session_id}/move")
def move_party(session_id: str, body: MoveIn, user: CurrentUser, db: DbDep):
    s = _get_owned_session(db, session_id, user)
    _, graph = _graph_for(s.map)
    if not graph.has_node(body.to):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown node '{body.to}'")
    nodes = set(s.discovered_nodes or [])
    doors = set(s.discovered_doors or [])
    _reveal(graph, body.to, nodes, doors)
    s.party_location = body.to
    s.discovered_nodes = sorted(nodes)
    s.discovered_doors = sorted(doors)
    db.commit()
    db.refresh(s)
    return _serialize(s, graph)


@router.post("/sessions/{session_id}/reveal")
def reveal_node(session_id: str, body: RevealIn, user: CurrentUser, db: DbDep):
    """GM reveal of a node (e.g. behind a secret door) without moving the
    party. Reveals the node's visible doors too unless told otherwise."""
    s = _get_owned_session(db, session_id, user)
    _, graph = _graph_for(s.map)
    if not graph.has_node(body.node):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown node '{body.node}'")
    nodes = set(s.discovered_nodes or [])
    doors = set(s.discovered_doors or [])
    if body.reveal_doors:
        _reveal(graph, body.node, nodes, doors)
    else:
        nodes.add(body.node)
    s.discovered_nodes = sorted(nodes)
    s.discovered_doors = sorted(doors)
    db.commit()
    db.refresh(s)
    return _serialize(s, graph)


@router.get("/sessions/{session_id}/render")
def render_session(
    session_id: str,
    user: CurrentUser,
    db: DbDep,
    view: str = "discovered",
    renderer: str | None = None,
):
    """Fog-of-war SVG. `view=discovered` (default) shows only explored
    geometry; `view=full` draws the whole map with the party marker."""
    s = _get_owned_session(db, session_id, user)
    dmap, _ = _graph_for(s.map)
    svg = render_fogged(
        dmap,
        set(s.discovered_nodes or []),
        set(s.discovered_doors or []),
        party_location=s.party_location,
        renderer=renderer,
        full=(view == "full"),
    )
    return {"svg": svg}
