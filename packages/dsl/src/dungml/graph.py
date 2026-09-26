"""Connectivity graph + pathfinding over a parsed `DungeonMap`.

A `.dmap` file already encodes a topological graph, even though it reads
as geometry: the *nodes* are rooms and corridors, and the *edges* are
doors. A door's `connects [room.a, corridor.b]` is literally an edge
between two nodes, and a corridor joining two rooms shows up as the
two-hop path `room.a -> corridor.b -> room.c`.

This module derives that graph and runs pathfinding *server-side* so a
consumer (the MCP server, the backend, a renderer doing fog-of-war)
never has to reconstruct spatial relationships from prose. Everything
here is a pure function of the parsed model — no I/O, no persistence.

Node ids are the same dotted references doors use: ``"room.NAME"`` and
``"corridor.NAME"``. Door identity is a stable key derived from the
door's position (see `door_key`), so a runtime play-session overlay can
refer to a door without the DSL needing explicit door ids.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from pydantic import BaseModel

from . import walk
from .model import Door, DungeonMap, Room, SourceSpan
from .walk import Placed

# A door state that physically blocks passage until something changes
# (a key, a check, brute force). Everything else — open, closed, ajar,
# unlocked — is treated as traversable: you can just walk through, or
# open it as you go.
BLOCKING_STATES = frozenset({"locked", "barred", "stuck", "sealed"})

# Door types that are concealed: present in the DM's authored map but not
# visible to players until explicitly discovered.
HIDDEN_DOOR_TYPES = frozenset({"secret", "hidden", "concealed"})

# Door types passable in one direction only — from the first `connects`
# reference to the second.
ONE_WAY_DOOR_TYPES = frozenset({"one-way", "oneway", "one_way"})


def _fmt(n: float) -> str:
    """Format a coordinate compactly: ``14.0 -> "14"``, ``9.5 -> "9.5"``."""
    i = int(n)
    return str(i) if n == i else str(n)


def is_concealed(door: Door) -> bool:
    """A door the players can't see until it's found: the `secret` flag, or
    a concealed type (`secret`, `hidden`, `concealed`)."""
    return door.secret or door.type in HIDDEN_DOOR_TYPES


def door_key(door: Door) -> str:
    """Stable identity for a door: its name (`door "vault" …`), else its
    position (e.g. ``"14,9"``).

    A position key changes when the author moves the door, which makes play
    sessions forget it was found; a name doesn't. Two doors at the exact
    same point are extremely unusual; `build_graph` disambiguates any
    genuine collision with a ``#N`` suffix so keys stay unique within a map.
    """
    if door.id:
        return door.id
    x, y = door.position
    return f"{_fmt(x)},{_fmt(y)}"


@dataclass(frozen=True)
class Node:
    """A room or corridor in the connectivity graph."""

    id: str  # "room.antechamber" / "corridor.passage"
    kind: str  # "room" | "corridor"
    name: str  # bare name without the kind prefix
    hidden: bool = False  # declared inside a `layer { hidden ... }`
    layer: Optional[str] = None  # owning layer name, if any


@dataclass(frozen=True)
class Edge:
    """A traversable connection between two nodes, backed by a door."""

    a: str  # node id
    b: str  # node id
    key: str  # door_key
    type: str  # door type (wooden, iron, secret, ...)
    state: str  # door state (open, closed, locked, ...)
    hidden: bool  # concealed door (secret/hidden type)
    one_way: bool = False  # passable from `a` to `b` only (a = first `connects`)

    def other(self, node: str) -> str:
        return self.b if node == self.a else self.a


@dataclass(frozen=True)
class BoundaryExit:
    """A door with a single `connects` ref — an opening to "outside" the
    mapped area (or a secret door whose far side is unmapped). Not part
    of the routable graph, but surfaced by `exits` so a caller can see
    that a wall has an opening."""

    node: str
    key: str
    type: str
    state: str
    hidden: bool


@dataclass
class Graph:
    """Derived connectivity graph for a single map."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    boundary: list[BoundaryExit] = field(default_factory=list)
    # node id -> list of incident edges
    _adj: dict[str, list[Edge]] = field(default_factory=dict)

    def has_node(self, node: str) -> bool:
        return node in self.nodes

    def neighbors(self, node: str) -> list[tuple[str, Edge]]:
        """`(neighbor_id, edge)` pairs for every edge incident to `node`."""
        return [(e.other(node), e) for e in self._adj.get(node, [])]

    def incident_edges(self, node: str) -> list[Edge]:
        return list(self._adj.get(node, []))

    def boundary_exits(self, node: str) -> list[BoundaryExit]:
        return [b for b in self.boundary if b.node == node]

    def find_path(
        self,
        src: str,
        dst: str,
        *,
        passable: Optional[Callable[[Edge], bool]] = None,
        node_ok: Optional[Callable[[str], bool]] = None,
    ) -> Optional["Path"]:
        """Shortest node-hop path from `src` to `dst`, or None.

        `passable(edge)` gates which edges may be traversed (default: all).
        `node_ok(node)` gates which nodes may be entered (default: all);
        `src` is always allowed as the starting point. Breadth-first, so
        the result minimises the number of doors passed through.
        """
        if src not in self.nodes or dst not in self.nodes:
            return None
        passable = passable or (lambda e: True)
        node_ok = node_ok or (lambda n: True)
        if src != dst and not node_ok(dst):
            return None
        if src == dst:
            return Path(nodes=[src], edges=[])

        # BFS, remembering the edge we arrived by so we can reconstruct.
        prev: dict[str, tuple[str, Edge]] = {}
        seen = {src}
        q: deque[str] = deque([src])
        while q:
            cur = q.popleft()
            if cur == dst:
                break
            for edge in self._adj.get(cur, []):
                if not passable(edge):
                    continue
                nxt = edge.other(cur)
                if nxt in seen:
                    continue
                if nxt != dst and not node_ok(nxt):
                    continue
                seen.add(nxt)
                prev[nxt] = (cur, edge)
                q.append(nxt)

        if dst not in prev and dst != src:
            return None
        # Walk back from dst to src.
        nodes_rev = [dst]
        edges_rev: list[Edge] = []
        cur = dst
        while cur != src:
            p, edge = prev[cur]
            edges_rev.append(edge)
            nodes_rev.append(p)
            cur = p
        return Path(nodes=list(reversed(nodes_rev)), edges=list(reversed(edges_rev)))


@dataclass
class Path:
    """A route through the graph: an alternating node/edge sequence."""

    nodes: list[str]
    edges: list[Edge]

    @property
    def length(self) -> int:
        """Number of doors traversed (graph hops)."""
        return len(self.edges)

    def to_dict(self) -> dict:
        return {
            "found": True,
            "nodes": list(self.nodes),
            "doors": [e.key for e in self.edges],
            "length": self.length,
            "steps": [
                {
                    "from": self.nodes[i],
                    "to": self.nodes[i + 1],
                    "door": e.key,
                    "type": e.type,
                    "state": e.state,
                }
                for i, e in enumerate(self.edges)
            ],
        }


def keyed_doors(dmap: DungeonMap) -> list[tuple[str, Placed]]:
    """Every door with the key `build_graph` gives it, in graph order.

    Keys are the door's position (`door_key`); a genuine collision — two
    doors at one point — gets a `#N` suffix in declaration order. Anything
    that needs to find "the door behind edge X" goes through this, so the
    suffixing is defined once.
    """
    out: list[tuple[str, Placed]] = []
    seen: set[str] = set()
    for p in walk.members(dmap, "doors"):
        key = door_key(p.item)
        if key in seen:
            n = 2
            while f"{key}#{n}" in seen:
                n += 1
            key = f"{key}#{n}"
        seen.add(key)
        out.append((key, p))
    return out


def build_graph(dmap: DungeonMap) -> Graph:
    """Derive the connectivity graph from a parsed map.

    Nodes are every room and corridor (across the top level and all
    layers); edges are doors with two or more `connects` references.
    A door with a single reference becomes a `BoundaryExit`. References
    to undefined nodes are skipped (validation reports those separately).
    """
    g = Graph()

    for kind in ("room", "corridor"):
        for p in walk.members(dmap, f"{kind}s"):
            nid = f"{kind}.{p.item.name}"
            g.nodes[nid] = Node(
                id=nid, kind=kind, name=p.item.name, hidden=p.hidden,
                layer=p.layer.name if p.layer is not None else None,
            )

    for key, placed in keyed_doors(dmap):
        door = placed.item
        refs = [r for r in door.connects if r in g.nodes]
        hidden = is_concealed(door)
        one_way = door.type in ONE_WAY_DOOR_TYPES
        if len(refs) == 1:
            g.boundary.append(
                BoundaryExit(
                    node=refs[0], key=key, type=door.type,
                    state=door.state, hidden=hidden,
                )
            )
        else:
            # Connect every unordered pair (almost always exactly one). For a
            # one-way door the pair stays ordered: `a` (first connects) → `b`.
            for i in range(len(refs)):
                for j in range(i + 1, len(refs)):
                    g.edges.append(
                        Edge(
                            a=refs[i], b=refs[j], key=key, type=door.type,
                            state=door.state, hidden=hidden, one_way=one_way,
                        )
                    )

    for edge in g.edges:
        g._adj.setdefault(edge.a, []).append(edge)
        # A one-way door is only traversable forward, so don't link it back.
        if not edge.one_way:
            g._adj.setdefault(edge.b, []).append(edge)

    return g


def is_blocked(state: str) -> bool:
    """True if a door in this state cannot be walked through as-is."""
    return state.lower() in BLOCKING_STATES


def _strip_dm_notes(obj: object) -> None:
    """Clear every `dm_notes` in a model tree, in place. Walks all fields
    rather than naming entity types, so a new entity kind can't leak."""
    if isinstance(obj, BaseModel):
        if getattr(obj, "dm_notes", None) is not None:
            obj.dm_notes = None
        for name in type(obj).model_fields:
            _strip_dm_notes(getattr(obj, name))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _strip_dm_notes(item)
    elif isinstance(obj, dict):
        for item in obj.values():
            _strip_dm_notes(item)


def _strip_spans(obj: object) -> None:
    """Reset every source span in a model tree, in place. The renderer
    anchors entities to their source lines for the editor; in the players'
    view the gaps between those lines would hint at what is hidden."""
    if isinstance(obj, SourceSpan):
        return
    if isinstance(obj, BaseModel):
        if isinstance(getattr(obj, "span", None), SourceSpan):
            obj.span = SourceSpan()
        for name in type(obj).model_fields:
            if name != "span":
                _strip_spans(getattr(obj, name))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _strip_spans(item)
    elif isinstance(obj, dict):
        for item in obj.values():
            _strip_spans(item)


def fog_of_war(
    dmap: DungeonMap,
    discovered_nodes: Iterable[str],
    discovered_doors: Iterable[str],
    revealed: Iterable[str] = (),
) -> DungeonMap:
    """Return a copy of `dmap` pruned to what a play-session has discovered.

    Secrets (see `dungml.secrets`) are hidden unless their key is in
    `revealed` — the DM's reveal list.

    Rooms and corridors not in `discovered_nodes` are dropped; doors not
    in `discovered_doors` are dropped; windows and location-bound markers
    whose host node is undiscovered are dropped too. Cross-cutting terrain
    (`slice`) and unanchored markers/features are kept — they're either
    landscape-scale or runtime tokens the GM placed deliberately.

    The result is a fully valid `DungeonMap` that any renderer can draw,
    giving fog-of-war for free without renderer changes.
    """
    nodes = set(discovered_nodes)
    doors = set(discovered_doors)

    from .secrets import is_secret, secret_key

    shown = set(revealed)

    def keep_window(in_ref: str) -> bool:
        return in_ref in nodes

    def keep_marker(location: Optional[str]) -> bool:
        return location is None or location in nodes

    def strip_secret(host, scope: str) -> None:
        # Secrets — features secret by instance or by type (core.dmap's
        # traps), and secret texts, areas, line features, markers and exits —
        # are GM-only: dropped even when their node is discovered, unless the
        # DM has revealed them. The GM's full view skips fog_of_war entirely.
        for kind in ("features", "exits", "texts", "areas", "line_features", "markers"):
            items = getattr(host, kind, None)
            if items:
                setattr(host, kind, [
                    it for it in items
                    if not is_secret(dmap, kind, it)
                    or secret_key(kind, it, scope) in shown
                ])

    out = dmap.model_copy(deep=True)
    # Freeze label numbers from the full map before pruning, so the players'
    # "3. Crypt" is the GM's "3. Crypt" rather than renumbered 1..n.
    numbered: dict[str, Room] = dict(out.rooms)
    for layer in out.layers:
        if not layer.hidden:
            for r in layer.rooms:
                numbered.setdefault(r.name, r)
    for i, r in enumerate(numbered.values()):
        if r.number is None:
            r.number = i + 1
    _strip_dm_notes(out)
    _strip_spans(out)
    strip_secret(out, "map")
    out.rooms = {n: r for n, r in out.rooms.items() if f"room.{n}" in nodes}
    out.corridors = {
        n: c for n, c in out.corridors.items() if f"corridor.{n}" in nodes
    }
    for r in out.rooms.values():
        strip_secret(r, f"room.{r.name}")
    for c in out.corridors.values():
        strip_secret(c, f"corridor.{c.name}")
    out.doors = [d for d in out.doors if door_key(d) in doors]

    # A door's `trapped` flag is GM-only knowledge — never expose it in the
    # discovered (players') view. The GM full view renders the map without
    # fog, so traps still show there.
    def _hide_traps(door_list: list[Door]) -> None:
        for d in door_list:
            if d.trapped:
                d.trapped = False

    _hide_traps(out.doors)
    out.windows = [w for w in out.windows if keep_window(w.in_ref)]
    out.markers = [m for m in out.markers if keep_marker(m.location)]

    for layer in out.layers:
        strip_secret(layer, f"layer.{layer.name}")
        layer.rooms = [r for r in layer.rooms if f"room.{r.name}" in nodes]
        layer.corridors = [
            c for c in layer.corridors if f"corridor.{c.name}" in nodes
        ]
        for r in layer.rooms:
            strip_secret(r, f"room.{r.name}")
        for c in layer.corridors:
            strip_secret(c, f"corridor.{c.name}")
        layer.doors = [d for d in layer.doors if door_key(d) in doors]
        _hide_traps(layer.doors)
        layer.windows = [w for w in layer.windows if keep_window(w.in_ref)]
        layer.markers = [m for m in layer.markers if keep_marker(m.location)]

    return out
