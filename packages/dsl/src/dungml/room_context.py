"""What a room is, for a caller that narrates it.

`graph` knows connectivity and `play` knows rendering; this module answers
"what is this room, and what may the players know about it". Every consumer
of room text — the backend's campaign contract, its sessions routes, the MCP
server — goes through here, so the rules for what is secret live in one place.

Output is split in two. `perceived` is what a character standing in the room
can see: boxed text, visible features, the ways out it has found. `dm_only`
is the rest: DM notes, unfound secret doors, traps, secret features. A caller
serving players drops `dm_only`; a caller serving the DM keeps both, so the DM
knows what not to say.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

from .geometry import _point_strictly_inside, corridor_polygons, room_polygon
from .graph import Graph, is_blocked
from .model import Corridor, DungeonMap, Room


@dataclass(frozen=True)
class SessionView:
    """The runtime overlay a play session carries, detached from any ORM."""

    discovered_nodes: frozenset[str] = frozenset()
    discovered_doors: frozenset[str] = frozenset()
    door_states: Mapping[str, str] = field(default_factory=dict)
    party_location: Optional[str] = None

    def state(self, key: str, authored: str) -> str:
        return self.door_states.get(key, authored)


# ----- lookup -----

def _nodes(dmap: DungeonMap) -> dict[str, Room | Corridor]:
    out: dict[str, Room | Corridor] = {}
    for name, r in dmap.rooms.items():
        out[f"room.{name}"] = r
    for name, c in dmap.corridors.items():
        out[f"corridor.{name}"] = c
    for layer in dmap.layers:
        for r in layer.rooms:
            out.setdefault(f"room.{r.name}", r)
        for c in layer.corridors:
            out.setdefault(f"corridor.{c.name}", c)
    return out


def node_label(dmap: DungeonMap, node_id: str) -> str:
    """Label text, else a corridor's display name, else the bare name."""
    obj = _nodes(dmap).get(node_id)
    bare = node_id.split(".", 1)[-1]
    if obj is None:
        return bare
    if obj.label is not None and obj.label.text:
        return obj.label.text
    display = getattr(obj, "display_name", None)
    return display or bare


def candidates(dmap: DungeonMap, graph: Graph, query: str) -> list[dict]:
    """Every node `query` could mean: exact id, bare name, label or display
    name, case-insensitive. An exact id or bare-name match wins outright."""
    q = (query or "").strip()
    if not q:
        return []
    if graph.has_node(q):
        return [{"id": q, "label": node_label(dmap, q)}]
    low = q.lower()
    bare = [nid for nid in graph.nodes if nid.split(".", 1)[-1].lower() == low]
    if len(bare) == 1:
        return [{"id": bare[0], "label": node_label(dmap, bare[0])}]
    hits = []
    for nid, obj in _nodes(dmap).items():
        if nid not in graph.nodes:
            continue
        names = {nid.split(".", 1)[-1].lower()}
        if obj.label is not None and obj.label.text:
            names.add(obj.label.text.strip().lower())
        if getattr(obj, "display_name", None):
            names.add(obj.display_name.strip().lower())
        if low in names:
            hits.append({"id": nid, "label": node_label(dmap, nid)})
    return sorted(hits, key=lambda h: h["id"])


def resolve_node(dmap: DungeonMap, graph: Graph, query: str) -> Optional[str]:
    """The node id `query` names, or None if it names none or several."""
    hits = candidates(dmap, graph, query)
    return hits[0]["id"] if len(hits) == 1 else None


# ----- geometry: which node a loose point belongs to -----

def _area(poly: list) -> float:
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
                   - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2.0


def _polys(nid: str, obj) -> list[list]:
    if nid.startswith("room."):
        return [room_polygon(obj)]
    return corridor_polygons(obj)


def _owner(dmap: DungeonMap, point) -> Optional[str]:
    """The smallest node whose outline contains `point` — caves drawn inside
    a canyon polygon own their own annotations."""
    best: tuple[float, str] | None = None
    for nid, obj in _nodes(dmap).items():
        for poly in _polys(nid, obj):
            if len(poly) >= 3 and _point_strictly_inside(point, poly):
                a = _area(poly)
                if best is None or a < best[0]:
                    best = (a, nid)
    return best[1] if best else None


# ----- exits -----

def node_exits(graph: Graph, node: str, view: SessionView, *,
               labels: Mapping[str, str]) -> tuple[list[dict], list[dict]]:
    """(perceived, secret) exits from `node`.

    Perceived: every non-concealed door and boundary opening, plus concealed
    ones the session has found, each with its effective state. Secret:
    concealed doors not yet found. `discovered` says whether the door itself
    has been seen, which callers use to split "known way out" from "the DM
    knows there is a door here the party hasn't noticed yet"."""
    perceived: list[dict] = []
    secret: list[dict] = []

    def entry(key, to, type_, authored):
        state = view.state(key, authored)
        return {
            "door": key,
            "to": to,
            "to_label": labels.get(to) if to else None,
            "type": type_,
            "state": state,
            "blocked": is_blocked(state),
            "discovered": key in view.discovered_doors,
            "far_side_explored": bool(to) and to in view.discovered_nodes,
        }

    for edge in graph.incident_edges(node):
        e = entry(edge.key, edge.other(node), edge.type, edge.state)
        if edge.hidden and edge.key not in view.discovered_doors:
            secret.append(e)
        else:
            perceived.append(e)
    for b in graph.boundary_exits(node):
        e = entry(b.key, None, b.type, b.state)
        if b.hidden and b.key not in view.discovered_doors:
            secret.append(e)
        else:
            perceived.append(e)
    return perceived, secret


# ----- the room -----

def _door_extras(dmap: DungeonMap) -> dict[str, object]:
    from .graph import door_key
    out = {}
    doors = list(dmap.doors)
    for layer in dmap.layers:
        doors.extend(layer.doors)
    for d in doors:
        out.setdefault(door_key(d), d)
    return out


def room_context(dmap: DungeonMap, graph: Graph, node: str, view: SessionView) -> dict:
    obj = _nodes(dmap)[node]
    labels = {nid: node_label(dmap, nid) for nid in graph.nodes}
    doors = _door_extras(dmap)
    secret_refs = {n for n, fd in dmap.feature_defs.items() if getattr(fd, "secret", False)}

    exits, secret_exits = node_exits(graph, node, view, labels=labels)
    for e in exits:
        d = doors.get(e["door"].split("#", 1)[0])
        if d is not None and d.description:
            e["description"] = d.description
    perceived_exits = [e for e in exits if e["discovered"]]
    undiscovered = [e for e in exits if not e["discovered"]]
    trapped = sorted(e["door"] for e in exits + secret_exits
                     if getattr(doors.get(e["door"].split("#", 1)[0]), "trapped", False))
    door_notes = [{"door": e["door"], "dm_notes": doors[e["door"].split("#", 1)[0]].dm_notes}
                  for e in exits + secret_exits
                  if getattr(doors.get(e["door"].split("#", 1)[0]), "dm_notes", None)]

    # Features: described ones individually, plain ones counted by kind.
    features: list[dict] = []
    counts: dict[str, int] = {}
    secret_features: list[dict] = []
    for f in obj.features:
        if f.secret or f.ref in secret_refs:
            item = {"name": f.ref}
            if f.description:
                item["description"] = f.description
            if f.dm_notes:
                item["dm_notes"] = f.dm_notes
            secret_features.append(item)
        elif f.description:
            features.append({"name": f.ref, "description": f.description})
        else:
            counts[f.ref] = counts.get(f.ref, 0) + 1
    features.extend({"name": n, "count": c} for n, c in sorted(counts.items()))
    feature_notes = [{"name": f.ref, "dm_notes": f.dm_notes} for f in obj.features
                     if f.dm_notes and not (f.secret or f.ref in secret_refs)]

    # Annotations: the node's own texts plus map-level texts inside it.
    texts = list(obj.texts) + [t for t in list(dmap.texts) + [t for l in dmap.layers for t in l.texts]
                               if _owner(dmap, t.position) == node]
    annotations = []
    annotation_notes = []
    for t in texts:
        a = {"text": t.text}
        if t.description:
            a["description"] = t.description
        annotations.append(a)
        if t.dm_notes:
            annotation_notes.append({"text": t.text, "dm_notes": t.dm_notes})

    # Cross-map exits: the node's own plus map-level ones inside it.
    xs = list(obj.exits) + [x for x in list(dmap.exits) + [x for l in dmap.layers for x in l.exits]
                            if _owner(dmap, x.position) == node]
    map_exits, secret_map_exits = [], []
    for x in xs:
        item = {"target_map": x.target_map,
                "label": x.label.text if x.label is not None else None}
        if x.description:
            item["description"] = x.description
        (secret_map_exits if x.secret else map_exits).append(item)

    return {
        "id": node,
        "kind": graph.nodes[node].kind,
        "label": labels[node],
        "discovered": node in view.discovered_nodes,
        "party_here": view.party_location == node,
        "perceived": {
            "description": obj.description,
            "features": features,
            "annotations": annotations,
            "exits": perceived_exits,
            "map_exits": map_exits,
        },
        "dm_only": {
            "notes": obj.dm_notes,
            "secret_exits": secret_exits,
            "undiscovered_exits": undiscovered,
            "trapped_doors": trapped,
            "door_notes": door_notes,
            "secret_features": secret_features,
            "feature_notes": feature_notes,
            "annotation_notes": annotation_notes,
            "secret_map_exits": secret_map_exits,
        },
    }


def known_map(dmap: DungeonMap, graph: Graph, view: SessionView) -> dict:
    """The discovered part of the map: nodes, connections between them, and
    the frontier — found doors leading somewhere not yet explored."""
    labels = {nid: node_label(dmap, nid) for nid in graph.nodes}
    nodes = [{"id": nid, "kind": graph.nodes[nid].kind, "label": labels[nid]}
             for nid in sorted(view.discovered_nodes) if nid in graph.nodes]
    connections, frontier, seen = [], [], set()
    for nid in sorted(view.discovered_nodes):
        if nid not in graph.nodes:
            continue
        for edge in graph.incident_edges(nid):
            if edge.key not in view.discovered_doors or edge.key in seen:
                continue
            seen.add(edge.key)
            state = view.state(edge.key, edge.state)
            a_in, b_in = edge.a in view.discovered_nodes, edge.b in view.discovered_nodes
            if a_in and b_in:
                connections.append({"door": edge.key, "between": [edge.a, edge.b],
                                    "type": edge.type, "state": state})
            else:
                known, unknown = (edge.a, edge.b) if a_in else (edge.b, edge.a)
                frontier.append({"door": edge.key, "from": known, "leads_to": unknown,
                                 "leads_to_label": labels[unknown],
                                 "type": edge.type, "state": state})
    return {"party_location": view.party_location, "nodes": nodes,
            "connections": connections, "frontier": frontier}
