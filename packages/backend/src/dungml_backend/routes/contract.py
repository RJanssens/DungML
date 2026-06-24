# packages/backend/src/dungml_backend/routes/contract.py
"""ttrpg3↔dungml map contract (root-mounted: /maps/{external_id}/…).

Adapts an external instance_id to dungml's Project→Map→PlaySession model. Pushes
are best-effort and degrade gracefully (the caller treats failures as no-ops);
the render token is a per-map HMAC grant minted here and verified by /render."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from dungml import build_graph, parse, visible_doors
from dungml.errors import DmapParseError

from .. import contract, render_token
from ..deps import CurrentService, DbDep

router = APIRouter(tags=["contract"])


class FragmentIn(BaseModel):
    dungml: str
    name: str | None = None


class RevealIn(BaseModel):
    feature_id: str


class TokenIn(BaseModel):
    scope: str = "fog"


@router.post("/maps/{external_id}/fragments")
def add_fragment(external_id: str, body: FragmentIn, _svc: CurrentService, db: DbDep) -> dict:
    m = contract.get_or_create_map(db, external_id)
    m.source = (m.source + "\n" + body.dungml) if m.source else body.dungml
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


@router.post("/maps/{external_id}/tokens")
def mint_token(external_id: str, body: TokenIn, _svc: CurrentService, db: DbDep) -> dict:
    contract.get_or_create_map(db, external_id)  # ensure it exists
    scope = "gm" if body.scope == "gm" else "fog"
    try:
        token = render_token.mint(external_id, scope)
    except render_token.TokenError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {"token": token}
