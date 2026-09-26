"""Door positions computed from the geometry: `door between A and B`.

Resolved once, after parsing and include-merging (a `between` may name a
room from a layer or an include), so every consumer — renderer, graph,
fog, validator, sessions — sees an ordinary positioned door.

- two rooms: the middle of their longest shared wall;
- a room and a corridor: where the corridor meets the room — the corridor
  end nearest the room's outline (projected onto it, so an end that stops
  a little short or pokes a little in still lands on the wall), else where
  the centreline crosses the outline;
- two corridors: where one ends at the other — end to end, or into its
  side — else where their centrelines cross.

Spaces that don't meet are a parse error, pointing at the door's line.
"""
from __future__ import annotations

import math
from typing import Optional, Union

from shapely.geometry import LineString, MultiLineString, Point, Polygon

from . import walk
from .errors import DmapParseError
from .geometry import LineWall, overlap_segment, room_polygon, room_walls
from .model import Corridor, Door, DungeonMap, Room, Vec2
from .walls import _terminal_ends, centerline_chains

REACH = 1.0  # how far a corridor end may sit from the outline it meets


def _clean(p: Vec2) -> Vec2:
    return (round(p[0], 6) + 0.0, round(p[1], 6) + 0.0)


def _centreline(c: Corridor) -> Optional[Union[LineString, MultiLineString]]:
    chains = centerline_chains(c)
    if not chains:
        return None
    return LineString(chains[0]) if len(chains) == 1 else MultiLineString(chains)


def _first_point(geom) -> Optional[Vec2]:
    if geom.is_empty:
        return None
    for g in getattr(geom, "geoms", [geom]):
        if isinstance(g, Point):
            return (g.x, g.y)
        coords = list(getattr(g, "coords", []))
        if coords:
            return coords[0]
    return None


def _room_room(a: Room, b: Room) -> Optional[Vec2]:
    best: Optional[tuple[float, Vec2]] = None
    for wa in room_walls(a):
        for wb in room_walls(b):
            if not (isinstance(wa, LineWall) and isinstance(wb, LineWall)):
                continue
            seg = overlap_segment(wa, wb)
            if seg is None:
                continue
            length = math.dist(*seg)
            if best is None or length > best[0]:
                best = (length, ((seg[0][0] + seg[1][0]) / 2, (seg[0][1] + seg[1][1]) / 2))
    return best[1] if best else None


def _room_corridor(room: Room, c: Corridor) -> Optional[Vec2]:
    outline = Polygon(room_polygon(room)).buffer(0).boundary
    ends = [p for p, _u, _l in _terminal_ends(c, centerline_chains(c))]
    near = [(outline.distance(Point(p)), p) for p in ends]
    near = [(d, p) for d, p in near if d <= REACH]
    if near:
        _, p = min(near)
        on = outline.interpolate(outline.project(Point(p)))
        return (on.x, on.y)
    line = _centreline(c)
    return _first_point(line.intersection(outline)) if line is not None else None


def _corridor_corridor(a: Corridor, b: Corridor) -> Optional[Vec2]:
    for one, other in ((a, b), (b, a)):
        line = _centreline(other)
        if line is None:
            continue
        reach = other.width / 2 + 0.5
        near = [
            (line.distance(Point(p)), p)
            for p, _u, _l in _terminal_ends(one, centerline_chains(one))
        ]
        near = [(d, p) for d, p in near if d <= reach]
        if near:
            return min(near)[1]
    la, lb = _centreline(a), _centreline(b)
    if la is None or lb is None:
        return None
    return _first_point(la.intersection(lb))


def _place(door: Door, rooms: dict, corridors: dict) -> Vec2:
    a, b = door.between or ["", ""]
    spaces = []
    for ref in (a, b):
        kind, _, name = ref.partition(".")
        table = rooms if kind == "room" else corridors if kind == "corridor" else {}
        if name not in table:
            raise DmapParseError(
                f"door between {a} and {b}: no such room or corridor '{ref}'",
                line=door.span.line, column=door.span.column,
            )
        spaces.append((kind, table[name]))
    (ka, sa), (kb, sb) = spaces
    if ka == kb == "room":
        pos = _room_room(sa, sb)
    elif ka == kb == "corridor":
        pos = _corridor_corridor(sa, sb)
    else:
        room, corr = (sa, sb) if ka == "room" else (sb, sa)
        pos = _room_corridor(room, corr)
    if pos is None:
        raise DmapParseError(
            f"door between {a} and {b}: they don't meet — no shared wall, and no "
            f"corridor end within {REACH} of the other",
            line=door.span.line, column=door.span.column,
        )
    return _clean(pos)


def resolve_door_placements(dmap: DungeonMap) -> None:
    """Fill in the position of every `between` door, in place."""
    pending = [p.item for p in walk.members(dmap, "doors") if p.item.between]
    if not pending:
        return
    rooms, corridors = walk.rooms(dmap), walk.corridors(dmap)
    for door in pending:
        door.position = _place(door, rooms, corridors)
