# packages/backend/src/dungml_backend/routes/contract.py
"""ttrpg3↔dungml map contract (root-mounted: /maps/{external_id}/…).

Adapts an external instance_id to dungml's Project→Map→PlaySession model. Pushes
are best-effort and degrade gracefully (the caller treats failures as no-ops);
the render token is a per-map HMAC grant minted here and verified by /render."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from dungml import build_graph, parse, render_fogged, visible_doors
from dungml.errors import DmapParseError

from .. import contract, render_token
from ..deps import CurrentService, DbDep

router = APIRouter(tags=["contract"])

_PLACEHOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="60">'
    '<text x="10" y="35" font-size="12">map not ready</text></svg>'
)


class FragmentIn(BaseModel):
    dungml: str
    name: str | None = None


class RevealIn(BaseModel):
    feature_id: str


class PartyIn(BaseModel):
    room_id: str


class SourceIn(BaseModel):
    dungml: str


class TokenIn(BaseModel):
    scope: str = "fog"


@router.post("/maps/{external_id}/fragments")
def add_fragment(external_id: str, body: FragmentIn, _svc: CurrentService, db: DbDep) -> dict:
    m = contract.get_or_create_map(db, external_id)
    m.source = (m.source + "\n" + body.dungml) if m.source else body.dungml
    db.commit()
    return {"ok": True}


@router.put("/maps/{external_id}/source")
def replace_source(external_id: str, body: SourceIn, _svc: CurrentService, db: DbDep) -> dict:
    """Replace the whole map source, rather than appending to it.

    /fragments is append-only, which suits a caller that discovers its map a
    piece at a time. A caller that *owns* the map and re-emits it whole on
    every change (ttrpg2 rewrites its combatant marker block per token move)
    needs replace instead — appending would stack duplicate geometry.

    Discovery is deliberately left alone: the fog overlay lives on the
    PlaySession and node ids are stable across re-emissions, so a redraw of
    the same rooms keeps whatever the party had already explored.
    """
    m = contract.get_or_create_map(db, external_id)
    m.source = body.dungml
    db.commit()
    return {"ok": True}


@router.post("/maps/{external_id}/reveal")
def reveal(external_id: str, body: RevealIn, _svc: CurrentService, db: DbDep) -> dict:
    m = contract.get_or_create_map(db, external_id)
    s = contract.session_for(db, m)
    try:
        graph = build_graph(parse(m.source))
    except DmapParseError:
        return {"ok": True}  # source not yet a full map — nothing to reveal
    if not graph.has_node(body.feature_id):
        return {"ok": True}  # unknown node — graceful no-op
    nodes = set(s.discovered_nodes or [])
    doors = set(s.discovered_doors or [])
    nodes.add(body.feature_id)
    doors |= visible_doors(graph, body.feature_id)
    s.discovered_nodes = sorted(nodes)
    s.discovered_doors = sorted(doors)
    db.commit()
    return {"ok": True}


@router.post("/maps/{external_id}/party")
def set_party(external_id: str, body: PartyIn, _svc: CurrentService, db: DbDep) -> dict:
    """Move the party marker to a node and reveal it (+ its visible doors).

    The campaigns contract has had this since authored-map play; the legacy
    /maps contract only had /reveal, so a caller that owned its own DSL could
    light up rooms but never say where the party was standing — and
    render_fogged draws the party marker from `party_location`.
    Graceful no-op on an unparseable source or unknown node, like /reveal.
    """
    m = contract.get_or_create_map(db, external_id)
    s = contract.session_for(db, m)
    try:
        graph = build_graph(parse(m.source))
    except DmapParseError:
        return {"ok": True}
    if not graph.has_node(body.room_id):
        return {"ok": True}
    nodes = set(s.discovered_nodes or [])
    doors = set(s.discovered_doors or [])
    nodes.add(body.room_id)
    doors |= visible_doors(graph, body.room_id)
    s.party_location = body.room_id
    s.discovered_nodes = sorted(nodes)
    s.discovered_doors = sorted(doors)
    db.commit()
    return {"ok": True}


@router.post("/maps/{external_id}/tokens")
def mint_token(external_id: str, body: TokenIn, _svc: CurrentService, db: DbDep) -> dict:
    contract.get_or_create_map(db, external_id)  # ensure it exists
    scope = "gm" if body.scope == "gm" else "fog"
    try:
        token = render_token.mint(external_id, scope)
    except render_token.TokenError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {"token": token}


@router.get("/maps/{external_id}/info")
def info(external_id: str, _svc: CurrentService, db: DbDep) -> dict:
    """Internal ids for an external_id, so ttrpg3 can mount the player widget.
    Idempotent (same get-or-create the other contract routes use)."""
    m = contract.get_or_create_map(db, external_id)
    s = contract.session_for(db, m)
    return {"map_id": str(m.id), "session_id": str(s.id)}


@router.get("/maps/{external_id}/render")
def render(external_id: str, token: str, db: DbDep) -> Response:
    # Token authorizes this endpoint (no CurrentService dep) — a plain <img src> works.
    try:
        scope = render_token.verify(token, external_id)
    except render_token.TokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e))
    m = contract.get_or_create_map(db, external_id)
    s = contract.session_for(db, m)
    try:
        dmap = parse(m.source)
    except DmapParseError:
        return Response(_PLACEHOLDER_SVG, media_type="image/svg+xml")
    svg = render_fogged(
        dmap,
        set(s.discovered_nodes or []),
        set(s.discovered_doors or []),
        party_location=s.party_location,
        full=(scope == "gm"),
    )
    return Response(svg, media_type="image/svg+xml")
