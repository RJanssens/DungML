# packages/backend/src/dungml_backend/contract.py
"""Lazy provisioning for the map contract: one service user owns a shared
service project; each external_id (ttrpg3 instance_id) maps to one Map + one
PlaySession. Idempotent get-or-create."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from fastapi import Response

from dungml import build_graph, candidates, parse, resolve_node, visible_doors
from dungml.errors import DmapParseError

from . import models

_SERVICE_SUBJECT = "@dungeon-daemon-service"
_SERVICE_PROJECT = "dungeon-daemon (service)"


def _service_user(db: DbSession) -> models.User:
    u = db.scalar(select(models.User).where(models.User.subject == _SERVICE_SUBJECT))
    if u is None:
        u = models.User(subject=_SERVICE_SUBJECT, email="service@dungml.local")
        db.add(u); db.commit(); db.refresh(u)
    return u


def _service_project(db: DbSession) -> models.Project:
    u = _service_user(db)
    p = db.scalar(
        select(models.Project).where(
            models.Project.user_id == u.id, models.Project.name == _SERVICE_PROJECT
        )
    )
    if p is None:
        # Private: ttrpg2 owns these maps and re-pushes their DSL on every token
        # move, so anyone else's edit would be silently overwritten.
        p = models.Project(user_id=u.id, name=_SERVICE_PROJECT, is_public=False)
        db.add(p); db.commit(); db.refresh(p)
    return p


def get_or_create_map(db: DbSession, external_id: str) -> models.Map:
    m = db.scalar(select(models.Map).where(models.Map.external_id == external_id))
    if m is None:
        p = _service_project(db)
        m = models.Map(project_id=p.id, name=f"instance {external_id}",
                        source="", external_id=external_id)
        db.add(m); db.commit(); db.refresh(m)
        session_for(db, m)  # ensure a play session exists
    return m


def session_for(db: DbSession, m: models.Map) -> models.PlaySession:
    s = db.scalar(select(models.PlaySession).where(models.PlaySession.map_id == m.id))
    if s is None:
        s = models.PlaySession(map_id=m.id, name="party")
        db.add(s); db.commit(); db.refresh(s)
    return s


def grant_service_access(db: DbSession, project: models.Project) -> None:
    """Make the campaign daemon a member of a project it drives.

    The service token already authenticates as an ordinary user; it simply
    had no authorization outside its own project, so ttrpg2 could move the
    party through the contract routes but couldn't read a map's source or add
    one of its own through `/api`. Membership closes that, and is why ttrpg2
    never needs to touch the database directly.

    Member rights, not owner rights: it cannot delete the project or manage
    who else is on it. It *can* edit the GM's authored maps — that boundary
    is policy (see ttrpg2's CLAUDE.md), not mechanism.
    """
    u = _service_user(db)
    if db.get(models.ProjectMember, (project.id, u.id)) is None:
        db.add(models.ProjectMember(project_id=project.id, user_id=u.id))
        db.commit()


def revoke_service_access(db: DbSession, project_id: str) -> None:
    """Drop the daemon's membership, unless another campaign still links here.

    Access must not outlive the link that justified it — but two campaigns on
    one project is the normal case, so unlinking one can't cut the other off.
    """
    remaining = db.scalar(
        select(models.CampaignLink).where(models.CampaignLink.project_id == project_id)
    )
    if remaining is not None:
        return
    u = _service_user(db)
    row = db.get(models.ProjectMember, (project_id, u.id))
    if row is not None:
        db.delete(row)
        db.commit()


def link_campaign(db: DbSession, external_id: str, project: models.Project) -> models.CampaignLink:
    """Upsert the campaign→project link. Caller must have verified access.

    Also moves the daemon's project membership to follow the link, including
    off the previous project when a campaign is re-linked elsewhere.
    """
    link = db.get(models.CampaignLink, external_id)
    previous_project_id = None
    if link is None:
        link = models.CampaignLink(
            external_id=external_id, project_id=project.id, user_id=project.user_id
        )
        db.add(link)
    else:
        previous_project_id = link.project_id
        link.project_id = project.id
        link.user_id = project.user_id
        if previous_project_id != project.id:
            # The active map belonged to the old project.
            link.active_map_id = None
    db.commit()
    db.refresh(link)
    grant_service_access(db, project)
    if previous_project_id and previous_project_id != project.id:
        revoke_service_access(db, previous_project_id)
    return link


def linked_project(db: DbSession, external_id: str) -> models.Project | None:
    link = db.get(models.CampaignLink, external_id)
    if link is None:
        return None
    return db.get(models.Project, link.project_id)


def map_in_link(db: DbSession, external_id: str, map_id: str) -> models.Map | None:
    """The Map iff external_id is linked and map_id belongs to that project."""
    proj = linked_project(db, external_id)
    if proj is None:
        return None
    m = db.get(models.Map, map_id)
    if m is None or m.project_id != proj.id:
        return None
    return m


def node_count(m: models.Map) -> int:
    """How many rooms/corridors a map has — the denominator for progress.

    0 for a map that doesn't parse: a map mid-edit must not break a read that
    spans a whole project.
    """
    try:
        return len(build_graph(parse(m.source)).nodes)
    except DmapParseError:
        return 0


def campaign_session_name(external_id: str) -> str:
    """How an externally-driven session shows up in the GUI's session list.

    Every campaign's session used to be called "party", which made the one
    ttrpg2 is driving indistinguishable from the GM's own saved sessions on
    the same map."""
    return f"ttrpg2 · {external_id}"


def campaign_session_for(db: DbSession, m: models.Map, external_id: str) -> models.PlaySession:
    """Get-or-create the per-campaign PlaySession for an authored map. Keyed by
    (map_id, external_id) so each campaign carries its own fog.

    Sessions created before campaign naming are still called "party"; those
    are renamed in passing, so no migration is needed. A name the GM chose
    themselves is left alone."""
    s = db.scalar(
        select(models.PlaySession).where(
            models.PlaySession.map_id == m.id,
            models.PlaySession.external_id == external_id,
        )
    )
    if s is None:
        s = models.PlaySession(
            map_id=m.id, external_id=external_id,
            name=campaign_session_name(external_id),
        )
        db.add(s); db.commit(); db.refresh(s)
    elif s.name == "party":
        s.name = campaign_session_name(external_id)
        db.commit(); db.refresh(s)
    return s


def set_active_map(db: DbSession, external_id: str, m: models.Map) -> models.CampaignLink:
    """Record which of the linked project's maps the campaign is playing on.
    Caller must have checked `map_in_link` first."""
    link = db.get(models.CampaignLink, external_id)
    if link is None:
        raise ValueError("campaign is not linked")
    link.active_map_id = m.id
    db.commit(); db.refresh(link)
    return link


def campaign_links_for_project(db: DbSession, project_id: str) -> list[models.CampaignLink]:
    return list(
        db.scalars(
            select(models.CampaignLink)
            .where(models.CampaignLink.project_id == project_id)
            .order_by(models.CampaignLink.created_at.asc())
        ).all()
    )


def load_graph(m: models.Map):
    """(DungeonMap, Graph) for a map. Raises DmapParseError mid-edit."""
    from dungml import build_graph, parse
    dmap = parse(m.source)
    return dmap, build_graph(dmap)


def session_view(s: models.PlaySession):
    from dungml import SessionView
    return SessionView(
        discovered_nodes=frozenset(s.discovered_nodes or []),
        discovered_doors=frozenset(s.discovered_doors or []),
        door_states=dict(s.door_states or {}),
        party_location=s.party_location,
        revealed=frozenset(s.revealed_secrets or []),
    )


def set_revealed(s: models.PlaySession, key: str, revealed: bool) -> None:
    """Add `key` to (or drop it from) a session's reveal list."""
    keys = set(s.revealed_secrets or [])
    keys = keys | {key} if revealed else keys - {key}
    s.revealed_secrets = sorted(keys)


def find_secret(dmap, key: str):
    """(secret, None) for a known key, else (None, candidate keys) — those
    containing `key` if any do, else every secret on the map."""
    from dungml.secrets import list_secrets
    secrets = list_secrets(dmap)
    for sc in secrets:
        if sc.key == key:
            return sc, None
    keys = [sc.key for sc in secrets]
    near = [k for k in keys if key and key in k]
    return None, sorted(near or keys)


def clear_party_elsewhere(db: DbSession, m: models.Map, external_id: str) -> None:
    """A party is on one map at a time: clear this campaign's marker on every
    other map before placing it on `m`."""
    others = (
        db.query(models.PlaySession)
        .filter(models.PlaySession.external_id == external_id,
                models.PlaySession.map_id != m.id,
                models.PlaySession.party_location.isnot(None))
        .all()
    )
    for s in others:
        s.party_location = None


def json_error(code: int, detail) -> Response:
    # Returned rather than raised: see routes/campaigns.map_rooms' note on the
    # app's SPA-fallback exception handler — a raised HTTPException on a
    # root-mounted GET would otherwise be rewritten into the SPA's index.html.
    import json as _json
    return Response(_json.dumps({"detail": detail}), status_code=code,
                    media_type="application/json")


def resolve_or_error(m: models.Map, query: str):
    """(dmap, graph, node_id) or an error Response (409 unparseable, 404 unknown)."""
    try:
        dmap, graph = load_graph(m)
    except DmapParseError:
        return json_error(409, "map does not parse — it may be mid-edit in the editor")
    node = resolve_node(dmap, graph, query)
    if node is None:
        return json_error(404, {"error": "unknown room", "query": query,
                                 "candidates": candidates(dmap, graph, query)[:20]})
    return dmap, graph, node


def discover(s: models.PlaySession, graph, node: str) -> None:
    nodes = set(s.discovered_nodes or [])
    doors = set(s.discovered_doors or [])
    nodes.add(node)
    doors |= visible_doors(graph, node)
    s.discovered_nodes = sorted(nodes)
    s.discovered_doors = sorted(doors)
