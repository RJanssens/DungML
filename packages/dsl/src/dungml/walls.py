"""Corridor wall geometry.

A corridor is drawn as a polygon — its centreline buffered by half its
width — and its walls are that polygon's outline, centred on the corridor's
edge exactly as a room's walls are centred on the room's. So a room built
against a corridor's side shares one wall line with it (not two lines half
a stroke apart, notching round every door).

Openings follow the connectivity graph, not overlaps:

- Where a corridor ends at a door, the end is *snapped* onto the wall the
  door sits on (a room wall, or another corridor's outline): extended if it
  stops short, trimmed if it pokes through, squared to the wall if it meets
  it at an angle. The corridor's end wall then coincides with the host wall,
  and the door cuts one door-wide gap through both — a narrow door in a wide
  corridor stays narrow.
- An exit at a corridor end leaves that end open.
- Everything else is wall: dead ends close themselves, and two corridors
  that merely cross keep their walls (one passes over the other), because
  without a door the party can't turn from one into the other.

Room walls are not built here; the renderer draws those itself.
Pure functions over the parsed model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from . import walk
from .geometry import LineWall, project_onto_wall, room_polygon
from .graph import is_concealed
from .model import ArcSegment, Corridor, Door, DungeonMap, LineSegment, Vec2

_EPS = 1e-6
DOOR_TOLERANCE = 1.0  # how far a door may sit from the wall it opens


@dataclass
class CorridorOutline:
    corridor: Corridor
    polygon: BaseGeometry  # Polygon or MultiPolygon — the floor out to the wall line
    wall_paths: list[list[Vec2]] = field(default_factory=list)  # closed if p[0]==p[-1]
    _segments: list[LineWall] = field(default_factory=list, repr=False)

    def nearest_wall(
        self, p: Vec2, tol: float = DOOR_TOLERANCE
    ) -> Optional[tuple[LineWall, float, float]]:
        """`(wall segment, t, distance)` of the outline segment nearest `p`."""
        return _nearest(self._segments, p, tol)


# ----- centreline -----

def _unit(dx: float, dy: float) -> Vec2:
    n = math.hypot(dx, dy) or 1.0
    return (dx / n, dy / n)


def _close(p: Vec2, q: Vec2) -> bool:
    return abs(p[0] - q[0]) <= _EPS and abs(p[1] - q[1]) <= _EPS


def _arc_points(s: ArcSegment) -> list[Vec2]:
    a0 = math.radians(s.from_angle)
    a1 = math.radians(s.to_angle)
    if s.sweep == "cw" and a1 > a0:
        a1 -= 2 * math.pi
    elif s.sweep == "ccw" and a1 < a0:
        a1 += 2 * math.pi
    steps = max(12, int(abs(math.degrees(a1 - a0)) // 5) + 1)
    cx, cy = s.center
    return [
        (cx + s.radius * math.cos(a0 + (a1 - a0) * i / steps),
         cy + s.radius * math.sin(a0 + (a1 - a0) * i / steps))
        for i in range(steps + 1)
    ]


def centerline_chains(corr: Corridor) -> list[list[Vec2]]:
    """The centreline as contiguous point chains — the same sub-paths the
    renderer strokes: a new chain wherever a segment doesn't continue from
    the previous one, or doubles back on it."""
    chains: list[list[Vec2]] = []
    prev_dir: Optional[Vec2] = None
    for s in corr.segments:
        pts = [s.start, s.end] if isinstance(s, LineSegment) else _arc_points(s)
        d = _unit(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
        contiguous = bool(chains) and _close(chains[-1][-1], pts[0])
        u_turn = (
            contiguous and prev_dir is not None
            and d[0] * prev_dir[0] + d[1] * prev_dir[1] < -0.999
        )
        if contiguous and not u_turn:
            chains[-1].extend(pts[1:])
        else:
            chains.append(list(pts))
        prev_dir = d
    return [c for c in chains if len(c) >= 2]


def _terminal_ends(corr: Corridor, chains: list[list[Vec2]]) -> list[tuple[Vec2, Vec2, float]]:
    """`(point, outward unit direction, length of the last leg)` for every
    free end — a segment endpoint no other segment shares."""
    ends: list[Vec2] = []
    for s in corr.segments:
        if isinstance(s, LineSegment):
            ends += [s.start, s.end]
        else:
            pts = _arc_points(s)
            ends += [pts[0], pts[-1]]
    out: list[tuple[Vec2, Vec2, float]] = []
    for ch in chains:
        for p, q in ((ch[0], ch[1]), (ch[-1], ch[-2])):
            if sum(1 for e in ends if _close(e, p)) == 1:
                out.append((p, _unit(p[0] - q[0], p[1] - q[1]), math.dist(p, q)))
    return out


def _buffer_chains(chains: list[list[Vec2]], r: float, join: str) -> BaseGeometry:
    return unary_union([
        LineString(ch).buffer(r, cap_style="flat", join_style=join, mitre_limit=10.0)
        for ch in chains
    ])


# ----- rings and segments -----

def _rings(poly: BaseGeometry) -> list[list[Vec2]]:
    geoms = getattr(poly, "geoms", [poly])
    out: list[list[Vec2]] = []
    for g in geoms:
        if g.is_empty or not isinstance(g, Polygon):
            continue
        for ring in (g.exterior, *g.interiors):
            out.append([(float(x), float(y)) for x, y in ring.coords])
    return out


def _nearest(
    segments: list[LineWall], p: Vec2, tol: float
) -> Optional[tuple[LineWall, float, float]]:
    best: Optional[tuple[LineWall, float, float]] = None
    for w in segments:
        _, t, dist = project_onto_wall(p, w)
        if best is None or dist < best[2]:
            best = (w, t, dist)
    return best if best is not None and best[2] <= tol else None


# ----- snapping a corridor end onto the wall its door sits on -----

def _touches(door: Door, corr: Corridor) -> bool:
    return not door.connects or f"corridor.{corr.name}" in door.connects


def _host_space(
    door: Door,
    corr: Corridor,
    rooms: dict,
    base: dict[str, BaseGeometry],
) -> Optional[BaseGeometry]:
    """The space on the far side of `door` from `corr`, as a shape: a room it
    connects (its outline as the renderer draws it), or another corridor it
    connects — whichever outline the door sits closest to."""
    best: Optional[tuple[float, BaseGeometry]] = None
    here = Point(door.position)
    for ref in door.connects:
        kind, _, name = ref.partition(".")
        if kind == "room" and name in rooms:
            shape: BaseGeometry = Polygon(room_polygon(rooms[name])).buffer(0)
        elif kind == "corridor" and name != corr.name and name in base:
            shape = base[name]
        else:
            continue
        dist = shape.boundary.distance(here)
        if dist <= DOOR_TOLERANCE and (best is None or dist < best[0]):
            best = (dist, shape)
    return best[1] if best is not None else None


def _entry_distance(start: Vec2, u: Vec2, reach: float, space: BaseGeometry) -> Optional[float]:
    """How far along `u` from `start` the ray enters `space` (0 if `start`
    is already inside), or None if it doesn't within `reach`."""
    if space.contains(Point(start)):
        return 0.0
    ray = LineString([start, (start[0] + u[0] * reach, start[1] + u[1] * reach)])
    inside = ray.intersection(space)
    if inside.is_empty:
        return None
    parts = getattr(inside, "geoms", [inside])
    return min(ray.project(Point(g.coords[0])) for g in parts if not g.is_empty)


def _snap_end(
    poly: BaseGeometry,
    p: Vec2,
    u: Vec2,
    r: float,
    width: float,
    space: BaseGeometry,
    join: str,
) -> BaseGeometry:
    """Extend / trim the corridor end at `p` (heading `u`) so it finishes
    exactly on the outline of `space` — along one wall, round a corner, or
    against a curve alike."""
    n = (-u[1], u[0])
    reach = width * 2 + 1  # a mismatched space must not drag the corridor far
    offsets = (-r, 0.0, r)
    starts = [(p[0] + n[0] * o, p[1] + n[1] * o) for o in offsets]
    entries = [_entry_distance(st, u, reach, space) for st in starts]
    if all(e is None for e in entries):
        return poly  # the end doesn't face this space at all
    # Carry each side forward to where it enters the space (plus a hair, so
    # the piece overlaps the space and the cut below leaves no sliver). A side
    # that never enters — the corridor grazes past a corner — ends where the
    # corridor was authored to end.
    ends = [
        (st[0] + u[0] * (e + 0.05), st[1] + u[1] * (e + 0.05)) if e is not None else st
        for st, e in zip(starts, entries)
    ]
    piece = Polygon([starts[0], ends[0], ends[1], ends[2], starts[2]]).buffer(0)
    poly = poly.union(piece)
    far = max(e for e in entries if e is not None)
    # Everything of this end that lies inside the space goes.
    return poly.difference(space.intersection(Point(p).buffer(far + 2 * r + 1)))


# ----- cutting door / exit openings into the outline -----

def _apply_cuts(
    segments_by_ring: list[list[LineWall]],
    cuts: list[tuple[Vec2, float]],
) -> list[list[Vec2]]:
    """Cut each `(position, width)` opening from the nearest outline segment,
    then chain what is left of each ring into polylines."""
    flat = [(ri, si, s) for ri, ring in enumerate(segments_by_ring) for si, s in enumerate(ring)]
    removed: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for pos, width in cuts:
        best = None
        for ri, si, s in flat:
            _, t, dist = project_onto_wall(pos, s)
            if best is None or dist < best[0]:
                best = (dist, ri, si, s, t)
        if best is None or best[0] > DOOR_TOLERANCE:
            continue
        _, ri, si, s, t = best
        # The gap runs along the nearest segment's line and through every segment
        # on that line it spans: one straight wall is often several outline
        # segments (a corridor end snapped onto another picks up its vertices).
        L = math.dist(s.a, s.b) or 1.0
        u = ((s.b[0] - s.a[0]) / L, (s.b[1] - s.a[1]) / L)
        c = _lerp(s, t)
        g0 = (c[0] - u[0] * width / 2, c[1] - u[1] * width / 2)
        g1 = (c[0] + u[0] * width / 2, c[1] + u[1] * width / 2)
        for rj, sj, w in flat:
            if not all(abs((q[0] - s.a[0]) * u[1] - (q[1] - s.a[1]) * u[0]) <= 1e-6 for q in (w.a, w.b)):
                continue                        # not on the nearest segment's line
            Lw = math.dist(w.a, w.b) or 1.0
            ta = ((g0[0] - w.a[0]) * (w.b[0] - w.a[0]) + (g0[1] - w.a[1]) * (w.b[1] - w.a[1])) / (Lw * Lw)
            tb = ((g1[0] - w.a[0]) * (w.b[0] - w.a[0]) + (g1[1] - w.a[1]) * (w.b[1] - w.a[1])) / (Lw * Lw)
            lo, hi = min(ta, tb), max(ta, tb)
            if hi > _EPS and lo < 1 - _EPS:
                removed.setdefault((rj, sj), []).append((lo, hi))

    paths: list[list[Vec2]] = []
    for ri, ring in enumerate(segments_by_ring):
        pieces: list[tuple[Vec2, Vec2]] = []
        for si, s in enumerate(ring):
            spans = sorted(removed.get((ri, si), []))
            t0 = 0.0
            for lo, hi in spans + [(1.0, 1.0)]:
                lo, hi = max(0.0, lo), min(1.0, hi)
                if lo > t0 + _EPS:
                    pieces.append((_lerp(s, t0), _lerp(s, lo)))
                t0 = max(t0, hi)
        # Chain consecutive pieces; join the wrap-around of a closed ring.
        chained: list[list[Vec2]] = []
        for a, b in pieces:
            if chained and _close(chained[-1][-1], a):
                chained[-1].append(b)
            else:
                chained.append([a, b])
        if len(chained) > 1 and _close(chained[-1][-1], chained[0][0]):
            chained[0] = chained.pop() + chained[0][1:]
        paths.extend(chained)
    return paths


def _lerp(s: LineWall, t: float) -> Vec2:
    return (s.a[0] + (s.b[0] - s.a[0]) * t, s.a[1] + (s.b[1] - s.a[1]) * t)


# ----- entry point -----

def corridor_outlines(
    dmap: DungeonMap, *, wall_stroke: float, visible: bool = True
) -> dict[str, CorridorOutline]:
    """Outline, floor polygon and cut walls for every corridor with a width
    (zero-width corridors are drawn as a bare centreline elsewhere)."""
    corridors = walk.corridors(dmap, visible=visible)
    rooms = walk.rooms(dmap, visible=visible)
    doors: list[Door] = [p.item for p in walk.members(dmap, "doors", visible=visible)]
    exits = [p.item for p in walk.members(dmap, "exits", visible=visible)]
    default_corners = dmap.map.default_corners or "round"

    def join_of(c: Corridor) -> str:
        return "mitre" if (c.corners or default_corners) == "straight" else "round"

    wide = {n: c for n, c in corridors.items() if c.width > 0 and c.segments}
    chains = {n: centerline_chains(c) for n, c in wide.items()}
    radius = {n: c.width / 2 for n, c in wide.items()}
    base = {
        n: _buffer_chains(chains[n], radius[n], join_of(c))
        for n, c in wide.items()
        if chains[n]
    }

    out: dict[str, CorridorOutline] = {}
    for name, poly in base.items():
        c = wide[name]
        r = radius[name]
        tol = max(c.width / 2, 0.5) + 0.25
        cuts: list[tuple[Vec2, float]] = []
        for p, u, _leg in _terminal_ends(c, chains[name]):
            door = min(
                (d for d in doors if _touches(d, c) and math.dist(d.position, p) <= tol),
                key=lambda d: math.dist(d.position, p),
                default=None,
            )
            if door is not None:
                space = _host_space(door, c, rooms, base)
                if space is not None:
                    poly = _snap_end(poly, p, u, r, c.width, space, join_of(c))
            elif any(math.dist(ex.position, p) <= tol for ex in exits):
                cuts.append((p, 2 * r * 1.01))  # the map continues past this end
        for d in doors:
            if _touches(d, c) and not is_concealed(d):
                cuts.append((d.position, d.width or 1.0))
        rings = _rings(poly)
        segments_by_ring = [
            [LineWall(a, b) for a, b in zip(ring, ring[1:]) if math.dist(a, b) > _EPS]
            for ring in rings
        ]
        out[name] = CorridorOutline(
            corridor=c,
            polygon=poly,
            wall_paths=_apply_cuts(segments_by_ring, cuts),
            _segments=[s for ring in segments_by_ring for s in ring],
        )
    return out
