"""ttrpg3↔dungml campaign/multi-map contract (root-mounted: /campaigns/…).

Links an external campaign to a GM-owned project. link/unlink are GM-user
authorized; enumeration/render/reveal are service-scoped and bounded to linked
projects. Parallel to and independent of the legacy /maps/{external_id} routes."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from dungml import (
    build_graph,
    known_map,
    node_label,
    parse,
    render_fogged,
    resolve_node,
    room_context,
)
from dungml.errors import DmapParseError

from .. import access, contract, models, render_token
from ..deps import CurrentService, CurrentUser, DbDep

router = APIRouter(tags=["campaigns"])

_PLACEHOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="60">'
    '<text x="10" y="35" font-size="12">map not ready</text></svg>'
)


def _subject(external_id: str, map_id: str) -> str:
    """Composite render-token subject — binds a token to one (campaign, map)."""
    return f"{external_id}::{map_id}"


class LinkIn(BaseModel):
    project_id: str


class RevealIn(BaseModel):
    feature_id: str


class PartyIn(BaseModel):
    room_id: str


class SecretIn(BaseModel):
    key: str
    revealed: bool = True


class TokenIn(BaseModel):
    scope: str = "fog"


@router.post("/campaigns/{external_id}/link")
def link(external_id: str, body: LinkIn, user: CurrentUser, db: DbDep) -> dict:
    proj = access.accessible_project(db, body.project_id, user)
    if proj is None:
        # Treat unauthorized the same as missing — don't leak existence.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    existing_link = db.get(models.CampaignLink, external_id)
    if existing_link is not None:
        # Re-linking is fine for anyone who can reach the project the campaign
        # currently points at — the link records who created it, which must not
        # lock out the owner's collaborators. Anyone else gets the same no-leak
        # 404 as an unknown project.
        if access.accessible_project(db, existing_link.project_id, user) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    contract.link_campaign(db, external_id, proj)
    return {"external_id": external_id, "project_id": proj.id}


@router.delete("/campaigns/{external_id}/link", status_code=204)
def unlink(external_id: str, user: CurrentUser, db: DbDep) -> None:
    link_row = db.get(models.CampaignLink, external_id)
    if link_row is None:
        return  # idempotent
    proj = db.get(models.Project, link_row.project_id)
    if proj is not None and not access.can_access(db, proj, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    project_id = link_row.project_id
    db.delete(link_row)
    db.commit()
    # The daemon's access existed because of this link; it goes with it.
    contract.revoke_service_access(db, project_id)


class ActiveMapIn(BaseModel):
    map_id: str


@router.put("/campaigns/{external_id}/active")
def set_active_map(
    external_id: str, body: ActiveMapIn, _svc: CurrentService, db: DbDep
) -> dict:
    """Record the map this campaign is currently playing on.

    ttrpg2 owns the choice; it reports it here so the web app can send the GM
    straight to the live session. Bounded to the linked project, like every
    other service-scoped route."""
    m = contract.map_in_link(db, external_id, body.map_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "map not in linked project")
    link = contract.set_active_map(db, external_id, m)
    return {"external_id": external_id, "active_map_id": link.active_map_id}


@router.get("/campaigns/{external_id}/maps")
def list_maps(external_id: str, _svc: CurrentService, db: DbDep) -> list[dict]:
    proj = contract.linked_project(db, external_id)
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "campaign not linked")
    renderable = [m for m in proj.maps if m.kind == "map"]
    renderable.sort(key=lambda m: m.updated_at, reverse=True)
    return [
        {"id": m.id, "name": m.name, "is_default": m.is_default}
        for m in renderable
    ]


@router.post("/campaigns/{external_id}/maps/{map_id}/tokens")
def mint_token(external_id: str, map_id: str, body: TokenIn,
               _svc: CurrentService, db: DbDep) -> dict:
    if contract.map_in_link(db, external_id, map_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "map not found")
    scope = "gm" if body.scope == "gm" else "fog"
    try:
        token = render_token.mint(_subject(external_id, map_id), scope)
    except render_token.TokenError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {"token": token}


@router.get("/campaigns/{external_id}/maps/{map_id}/render")
def render(external_id: str, map_id: str, token: str, db: DbDep) -> Response:
    # Token authorizes this endpoint (no user dep) — a plain <img src> works.
    try:
        scope = render_token.verify(token, _subject(external_id, map_id))
    except render_token.TokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e))
    m = contract.map_in_link(db, external_id, map_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "map not found")
    s = contract.campaign_session_for(db, m, external_id)
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
        revealed=s.revealed_secrets or [],
    )
    return Response(svg, media_type="image/svg+xml")


@router.get("/campaigns/{external_id}/maps/{map_id}/rooms/{query}")
def room(external_id: str, map_id: str, query: str, _svc: CurrentService, db: DbDep,
         scope: Literal["gm", "fog"] = "gm"):
    m = contract.map_in_link(db, external_id, map_id)
    if m is None:
        return contract.json_error(404, "map not found")
    got = contract.resolve_or_error(m, query)
    if isinstance(got, Response):
        return got
    dmap, graph, node = got
    s = contract.campaign_session_for(db, m, external_id)
    ctx = room_context(dmap, graph, node, contract.session_view(s))
    if scope == "fog":
        ctx.pop("dm_only", None)
    return ctx


@router.get("/campaigns/{external_id}/maps/{map_id}/known")
def known(external_id: str, map_id: str, _svc: CurrentService, db: DbDep):
    m = contract.map_in_link(db, external_id, map_id)
    if m is None:
        return contract.json_error(404, "map not found")
    try:
        dmap, graph = contract.load_graph(m)
    except DmapParseError:
        return contract.json_error(409, "map does not parse — it may be mid-edit in the editor")
    s = contract.campaign_session_for(db, m, external_id)
    return known_map(dmap, graph, contract.session_view(s))


@router.post("/campaigns/{external_id}/maps/{map_id}/reveal")
def reveal(external_id: str, map_id: str, body: RevealIn,
           _svc: CurrentService, db: DbDep):
    m = contract.map_in_link(db, external_id, map_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "map not found")
    got = contract.resolve_or_error(m, body.feature_id)
    if isinstance(got, Response):
        return got
    dmap, graph, node = got
    s = contract.campaign_session_for(db, m, external_id)
    contract.discover(s, graph, node)
    db.commit()
    return {"ok": True, "revealed": node,
            "room": room_context(dmap, graph, node, contract.session_view(s))}


@router.post("/campaigns/{external_id}/maps/{map_id}/party")
def set_party(external_id: str, map_id: str, body: PartyIn,
              _svc: CurrentService, db: DbDep):
    """Move the party marker to a node (id, bare name or label) and reveal it
    and its visible doors. The party is on one map at a time: this clears the
    campaign's marker elsewhere and records this map as the active one."""
    m = contract.map_in_link(db, external_id, map_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "map not found")
    got = contract.resolve_or_error(m, body.room_id)
    if isinstance(got, Response):
        return got
    dmap, graph, node = got
    s = contract.campaign_session_for(db, m, external_id)
    contract.clear_party_elsewhere(db, m, external_id)
    contract.discover(s, graph, node)
    s.party_location = node
    contract.set_active_map(db, external_id, m)
    db.commit()
    return {"ok": True, "party_location": node,
            "room": room_context(dmap, graph, node, contract.session_view(s))}


class DoorIn(BaseModel):
    door: str | None = None
    between: list[str] | None = None
    discovered: bool = True
    state: str | None = None


@router.post("/campaigns/{external_id}/maps/{map_id}/doors")
def door(external_id: str, map_id: str, body: DoorIn, _svc: CurrentService, db: DbDep):
    """Record a found secret door and/or a runtime state (opened, forced,
    locked). The authored map never changes; this lives on the session."""
    m = contract.map_in_link(db, external_id, map_id)
    if m is None:
        return contract.json_error(404, "map not found")
    try:
        dmap, graph = contract.load_graph(m)
    except DmapParseError:
        return contract.json_error(409, "map does not parse — it may be mid-edit in the editor")
    key = body.door
    authored = None
    if key is None and body.between and len(body.between) == 2:
        a = resolve_node(dmap, graph, body.between[0])
        b = resolve_node(dmap, graph, body.between[1])
        hit = [e for e in graph.edges if {e.a, e.b} == {a, b}] if a and b else []
        if len(hit) > 1:
            return contract.json_error(404, {"error": "ambiguous door",
                                     "candidates": [e.key for e in hit]})
        key = hit[0].key if len(hit) == 1 else None
    for e in graph.edges:
        if e.key == key:
            authored = e.state
    for bx in graph.boundary:
        if bx.key == key:
            authored = bx.state
    if key is None or authored is None:
        return contract.json_error(404, {"error": "unknown door", "door": body.door,
                                 "between": body.between})
    s = contract.campaign_session_for(db, m, external_id)
    if body.discovered:
        s.discovered_doors = sorted(set(s.discovered_doors or []) | {key})
    if body.state:
        states = dict(s.door_states or {})
        states[key] = body.state
        s.door_states = states
    db.commit()
    return {"ok": True, "door": key,
            "state": (s.door_states or {}).get(key, authored),
            "discovered": key in (s.discovered_doors or [])}


@router.post("/campaigns/{external_id}/maps/{map_id}/secrets")
def secret(external_id: str, map_id: str, body: SecretIn, _svc: CurrentService, db: DbDep):
    """Show a secret (trap, hidden inscription, …) to the players — or hide
    it again with `revealed: false`. Keys come from a room's
    `dm_only.secrets`. The authored map never changes; this is the session."""
    m = contract.map_in_link(db, external_id, map_id)
    if m is None:
        return contract.json_error(404, "map not found")
    try:
        dmap = parse(m.source)
    except DmapParseError:
        return contract.json_error(409, "map does not parse — it may be mid-edit in the editor")
    sc, candidates = contract.find_secret(dmap, body.key)
    if sc is None:
        return contract.json_error(404, {"error": "unknown secret", "key": body.key,
                                         "candidates": candidates})
    s = contract.campaign_session_for(db, m, external_id)
    contract.set_revealed(s, sc.key, body.revealed)
    db.commit()
    return {"ok": True, "key": sc.key, "kind": sc.kind, "node": sc.node,
            "revealed": sc.key in (s.revealed_secrets or [])}


@router.get("/campaigns/{external_id}/maps/{map_id}/info")
def info(external_id: str, map_id: str, _svc: CurrentService, db: DbDep) -> dict:
    m = contract.map_in_link(db, external_id, map_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "map not found")
    s = contract.campaign_session_for(db, m, external_id)
    return {"map_id": str(m.id), "session_id": str(s.id)}


@router.get("/maps/{map_id}/rooms")
def map_rooms(map_id: str, _svc: CurrentService, db: DbDep) -> dict:
    """The map's room/corridor graph as [{id,name,kind,exits}] — map-keyed and
    session-independent (structure is authored truth, not per-campaign fog).
    Backs ttrpg3's list_map_rooms tool so the Referee can reveal by node id."""
    m = db.get(models.Map, map_id)
    if m is None or m.kind != "map":
        # A raised HTTPException would be caught by the app's SPA-fallback
        # exception handler (it rewrites GET 404s outside /api, /health,
        # /campaigns into the SPA's index.html with a 200 — this route's
        # path is root-mounted under /maps and isn't in that exclusion
        # list). Return the 404 Response directly so it bypasses exception
        # handling entirely and reaches the client as a real 404.
        return Response(
            content='{"detail":"map not found"}',
            status_code=status.HTTP_404_NOT_FOUND,
            media_type="application/json",
        )
    try:
        dmap = parse(m.source)
        graph = build_graph(dmap)
    except DmapParseError:
        return {"rooms": []}
    exits: dict[str, list[str]] = {nid: [] for nid in graph.nodes}
    secret: dict[str, list[str]] = {nid: [] for nid in graph.nodes}
    for e in graph.edges:
        bucket = secret if e.hidden else exits
        bucket[e.a].append(e.b)
        if not e.one_way:
            bucket[e.b].append(e.a)
    rooms = [
        {"id": n.id, "name": n.name, "kind": n.kind,
         "label": node_label(dmap, n.id), "hidden": n.hidden,
         "exits": sorted(set(exits[n.id])),
         "secret_exits": sorted(set(secret[n.id]))}
        for n in graph.nodes.values()
    ]
    return {"rooms": rooms}
