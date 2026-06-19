"""Play-session helpers: fog-of-war rendering with a party-location marker.

Builds on `graph.fog_of_war` (which prunes a map to the discovered subset)
and the renderer's `party_start` marker (a disc drawn at a world point).
Pure functions — state (what's discovered, where the party is) lives in the
caller (the backend's PlaySession row / the MCP session store).
"""
from __future__ import annotations

from typing import Iterable, Optional

from .geometry import _centroid, room_polygon
from .graph import Graph, fog_of_war
from .model import Corridor, DungeonMap, LineSegment, Room, Vec2
from .render import get_renderer


def _find_room(dmap: DungeonMap, name: str) -> Optional[Room]:
    room = dmap.rooms.get(name)
    if room is not None:
        return room
    for layer in dmap.layers:
        for r in layer.rooms:
            if r.name == name:
                return r
    return None


def _find_corridor(dmap: DungeonMap, name: str) -> Optional[Corridor]:
    corr = dmap.corridors.get(name)
    if corr is not None:
        return corr
    for layer in dmap.layers:
        for c in layer.corridors:
            if c.name == name:
                return c
    return None


def _corridor_centroid(c: Corridor) -> Optional[Vec2]:
    pts: list[Vec2] = list(c.nodes.values())
    if not pts:
        for s in c.segments:
            if isinstance(s, LineSegment):
                pts.append(s.start)
                pts.append(s.end)
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def node_centroid(dmap: DungeonMap, node_id: str) -> Optional[Vec2]:
    """A representative interior point for a `room.X` / `corridor.Y` node,
    used to place the party marker. None if the node can't be located."""
    kind, _, name = node_id.partition(".")
    if kind == "room":
        room = _find_room(dmap, name)
        if room is None:
            return None
        poly = room_polygon(room)
        return _centroid(poly) if poly else None
    if kind == "corridor":
        corr = _find_corridor(dmap, name)
        return _corridor_centroid(corr) if corr is not None else None
    return None


def visible_doors(graph: Graph, node: str) -> set[str]:
    """Door keys a party standing in `node` can see — every incident door
    and boundary opening that isn't concealed (secret doors stay hidden
    until explicitly revealed)."""
    keys: set[str] = set()
    for edge in graph.incident_edges(node):
        if not edge.hidden:
            keys.add(edge.key)
    for b in graph.boundary_exits(node):
        if not b.hidden:
            keys.add(b.key)
    return keys


def render_fogged(
    dmap: DungeonMap,
    discovered_nodes: Iterable[str],
    discovered_doors: Iterable[str],
    *,
    party_location: Optional[str] = None,
    renderer: Optional[str] = None,
    full: bool = False,
) -> str:
    """Render a play view.

    With `full=False` (default) the map is pruned to the discovered subset
    via `fog_of_war`, giving the players' view. With `full=True` the whole
    map is drawn (the GM's view) — handy for showing the party marker on the
    complete map. Either way, when `party_location` is a known node, a start
    marker is drawn at its centroid to track where the party is.
    """
    if full:
        view = dmap.model_copy(deep=True)
    else:
        view = fog_of_war(dmap, discovered_nodes, discovered_doors)
    if party_location:
        pos = node_centroid(view, party_location)
        if pos is not None:
            view.map.party_start = pos
    name = renderer or view.map.renderer
    return get_renderer(name)().render(view)
