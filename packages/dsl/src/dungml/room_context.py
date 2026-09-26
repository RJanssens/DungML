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

from .geometry import owner_node
from .secrets import is_secret, list_secrets
from . import walk
from .graph import Graph, is_blocked, keyed_doors
from .model import Corridor, DungeonMap, Room


@dataclass(frozen=True)
class SessionView:
    """The runtime overlay a play session carries, detached from any ORM."""

    discovered_nodes: frozenset[str] = frozenset()
    discovered_doors: frozenset[str] = frozenset()
    door_states: Mapping[str, str] = field(default_factory=dict)
    party_location: Optional[str] = None
    # Secret keys the DM has shown the players (see dungml.secrets).
    revealed: frozenset[str] = frozenset()

    def state(self, key: str, authored: str) -> str:
        return self.door_states.get(key, authored)


# ----- lookup -----

def _nodes(dmap: DungeonMap) -> dict[str, Room | Corridor]:
    return walk.nodes(dmap)


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

def _owner(dmap: DungeonMap, point) -> Optional[str]:
    return owner_node(dmap, point)


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

    seen_keys: set[str] = set()
    for edge in graph.incident_edges(node):
        seen_keys.add(edge.key)
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
    # One-way doors are only in `a`'s adjacency (build_graph never links `b`
    # back), so the far side never sees `incident_edges` return them at all —
    # they'd otherwise vanish from that room's exits entirely. Surface them
    # here as an explicitly blocked, one-way-tagged entry.
    for edge in graph.edges:
        if edge.one_way and edge.b == node and edge.key not in seen_keys:
            e = entry(edge.key, edge.other(node), edge.type, edge.state)
            e["blocked"] = True
            e["one_way"] = True
            if edge.hidden and edge.key not in view.discovered_doors:
                secret.append(e)
            else:
                perceived.append(e)
    return perceived, secret


# ----- the room -----

def _door_extras(dmap: DungeonMap) -> dict[str, object]:
    """Door objects keyed exactly as `build_graph` keys its edges (the same
    `keyed_doors`), so a colliding door's own extras (description, trapped,
    dm_notes) never bleed onto its neighbour at the same point."""
    return {key: p.item for key, p in keyed_doors(dmap)}


def _door_for(doors: Mapping[str, object], key: str):
    return doors.get(key)


def room_context(dmap: DungeonMap, graph: Graph, node: str, view: SessionView) -> dict:
    obj = _nodes(dmap)[node]
    labels = {nid: node_label(dmap, nid) for nid in graph.nodes}
    doors = _door_extras(dmap)
    secrets = list_secrets(dmap)
    key_of = {id(sc.item): sc.key for sc in secrets}

    def hidden(item, kind: str) -> bool:
        """GM-only right now: a secret the DM hasn't revealed. (One with no
        key — inside a hidden layer — can't be revealed at all.)"""
        return is_secret(dmap, kind, item) and key_of.get(id(item)) not in view.revealed

    exits, secret_exits = node_exits(graph, node, view, labels=labels)
    for e in exits:
        d = _door_for(doors, e["door"])
        if d is not None and d.description:
            e["description"] = d.description
    # A way out the party has seen, into a node it has never entered: the
    # door is perceived, what lies beyond is not. `to` stays (a node id is
    # what callers move or reveal with, never narrated); the name goes to
    # dm_only so the DM can still resolve it.
    perceived_exits, exit_labels = [], {}
    for e in exits:
        if not e["discovered"]:
            continue
        if e["to"] and not e["far_side_explored"]:
            exit_labels[e["door"]] = e["to_label"]
            e = dict(e, to_label=None)
        perceived_exits.append(e)
    undiscovered = [e for e in exits if not e["discovered"]]
    trapped = sorted(e["door"] for e in exits + secret_exits
                     if getattr(_door_for(doors, e["door"]), "trapped", False))
    door_notes = [{"door": e["door"], "dm_notes": _door_for(doors, e["door"]).dm_notes}
                  for e in exits + secret_exits
                  if getattr(_door_for(doors, e["door"]), "dm_notes", None)]

    # Features: described ones individually, plain ones counted by kind.
    features: list[dict] = []
    counts: dict[str, int] = {}
    secret_features: list[dict] = []
    for f in obj.features:
        if is_secret(dmap, "features", f):
            item = {"name": f.ref, "revealed": not hidden(f, "features")}
            if id(f) in key_of:
                item["key"] = key_of[id(f)]
            if f.description:
                item["description"] = f.description
            if f.dm_notes:
                item["dm_notes"] = f.dm_notes
            secret_features.append(item)
        if hidden(f, "features"):
            continue
        if f.description:
            features.append({"name": f.ref, "description": f.description})
        else:
            counts[f.ref] = counts.get(f.ref, 0) + 1
    features.extend({"name": n, "count": c} for n, c in sorted(counts.items()))
    feature_notes = [{"name": f.ref, "dm_notes": f.dm_notes} for f in obj.features
                     if f.dm_notes and not is_secret(dmap, "features", f)]

    # Annotations: the node's own texts plus map-level texts inside it. A
    # hidden layer is GM-only in its entirety — its texts never surface as
    # perceived annotations, only as a DM-side hint that something is there.
    visible_layer_texts = [t for l in dmap.layers if not l.hidden for t in l.texts]
    hidden_layer_texts = [t for l in dmap.layers if l.hidden for t in l.texts]
    texts = list(obj.texts) + [t for t in list(dmap.texts) + visible_layer_texts
                               if _owner(dmap, t.position) == node]
    hidden_texts = [t for t in hidden_layer_texts if _owner(dmap, t.position) == node]
    annotations = []
    annotation_notes = []
    for t in texts:
        if hidden(t, "texts"):
            continue
        a = {"text": t.text}
        if t.description:
            a["description"] = t.description
        annotations.append(a)
        if t.dm_notes:
            annotation_notes.append({"text": t.text, "dm_notes": t.dm_notes})
    hidden_annotations = [{"text": t.text, "hidden_layer": True} for t in hidden_texts]

    # Cross-map exits: the node's own plus map-level ones inside it. Exits
    # authored inside a hidden layer are GM-only regardless of their own
    # `secret` flag, for the same reason as the texts above.
    visible_layer_exits = [x for l in dmap.layers if not l.hidden for x in l.exits]
    hidden_layer_exits = [x for l in dmap.layers if l.hidden for x in l.exits]
    xs = list(obj.exits) + [x for x in list(dmap.exits) + visible_layer_exits
                            if _owner(dmap, x.position) == node]
    hidden_xs = [x for x in hidden_layer_exits if _owner(dmap, x.position) == node]

    def _exit_item(x) -> dict:
        item = {"target_map": x.target_map,
                "label": x.label.text if x.label is not None else None}
        if x.description:
            item["description"] = x.description
        return item

    map_exits, secret_map_exits = [], []
    for x in xs:
        if x.secret:
            item = dict(_exit_item(x), revealed=not hidden(x, "exits"))
            if id(x) in key_of:
                item["key"] = key_of[id(x)]
            secret_map_exits.append(item)
        if not hidden(x, "exits"):
            map_exits.append(_exit_item(x))
    for x in hidden_xs:
        secret_map_exits.append(_exit_item(x))

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
            "exit_labels": exit_labels,
            "trapped_doors": trapped,
            "door_notes": door_notes,
            "secret_features": secret_features,
            "feature_notes": feature_notes,
            "annotation_notes": annotation_notes,
            "hidden_annotations": hidden_annotations,
            "secret_map_exits": secret_map_exits,
            # Everything in this node the DM can reveal, and whether it is.
            "secrets": [
                {"key": sc.key, "kind": sc.kind, "label": sc.label,
                 "revealed": sc.key in view.revealed}
                for sc in secrets if sc.node == node
            ],
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
