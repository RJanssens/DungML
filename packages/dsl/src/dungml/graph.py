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

from .model import Corridor, Door, DungeonMap, Room

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


def door_key(door: Door) -> str:
    """Stable identity for a door, derived from its position.

    Doors have no authored id, so we key them by their ``x,y`` position
    (e.g. ``"14,9"``). Two doors at the exact same point are extremely
    unusual; `build_graph` disambiguates any genuine collision with a
    ``#N`` suffix so keys stay unique within one map.
    """
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


def _iter_rooms(dmap: DungeonMap) -> Iterable[tuple[str, Room, Optional[str], bool]]:
    """Yield `(name, room, layer_name, hidden)` for top-level + layer rooms."""
    for name, room in dmap.rooms.items():
        yield name, room, None, False
    for layer in dmap.layers:
        for room in layer.rooms:
            yield room.name, room, layer.name, layer.hidden


def _iter_corridors(
    dmap: DungeonMap,
) -> Iterable[tuple[str, Corridor, Optional[str], bool]]:
    for name, corr in dmap.corridors.items():
        yield name, corr, None, False
    for layer in dmap.layers:
        for corr in layer.corridors:
            yield corr.name, corr, layer.name, layer.hidden


def _iter_doors(dmap: DungeonMap) -> Iterable[Door]:
    yield from dmap.doors
    for layer in dmap.layers:
        yield from layer.doors


def build_graph(dmap: DungeonMap) -> Graph:
    """Derive the connectivity graph from a parsed map.

    Nodes are every room and corridor (across the top level and all
    layers); edges are doors with two or more `connects` references.
    A door with a single reference becomes a `BoundaryExit`. References
    to undefined nodes are skipped (validation reports those separately).
    """
    g = Graph()

    for name, _room, layer, hidden in _iter_rooms(dmap):
        nid = f"room.{name}"
        g.nodes.setdefault(
            nid, Node(id=nid, kind="room", name=name, hidden=hidden, layer=layer)
        )
    for name, _corr, layer, hidden in _iter_corridors(dmap):
        nid = f"corridor.{name}"
        g.nodes.setdefault(
            nid, Node(id=nid, kind="corridor", name=name, hidden=hidden, layer=layer)
        )

    seen_keys: set[str] = set()
    for door in _iter_doors(dmap):
        key = door_key(door)
        if key in seen_keys:  # disambiguate genuine position collisions
            n = 2
            while f"{key}#{n}" in seen_keys:
                n += 1
            key = f"{key}#{n}"
        seen_keys.add(key)

        refs = [r for r in door.connects if r in g.nodes]
        hidden = door.type in HIDDEN_DOOR_TYPES
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


def fog_of_war(
    dmap: DungeonMap,
    discovered_nodes: Iterable[str],
    discovered_doors: Iterable[str],
) -> DungeonMap:
    """Return a copy of `dmap` pruned to what a play-session has discovered.

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

    def keep_window(in_ref: str) -> bool:
        return in_ref in nodes

    def keep_marker(location: Optional[str]) -> bool:
        return location is None or location in nodes

    out = dmap.model_copy(deep=True)
    out.rooms = {n: r for n, r in out.rooms.items() if f"room.{n}" in nodes}
    out.corridors = {
        n: c for n, c in out.corridors.items() if f"corridor.{n}" in nodes
    }
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
        layer.rooms = [r for r in layer.rooms if f"room.{r.name}" in nodes]
        layer.corridors = [
            c for c in layer.corridors if f"corridor.{c.name}" in nodes
        ]
        layer.doors = [d for d in layer.doors if door_key(d) in doors]
        _hide_traps(layer.doors)
        layer.windows = [w for w in layer.windows if keep_window(w.in_ref)]
        layer.markers = [m for m in layer.markers if keep_marker(m.location)]

    return out
