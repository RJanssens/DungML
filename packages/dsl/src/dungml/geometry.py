"""Edges, shared-edge detection, and door-opening helpers.

Renderers use this module to:

- Enumerate the wall segments of a room (line + arc walls).
- Find collinear-overlapping segments shared between two rooms.
- Project a door/window position onto the wall it sits on so a gap can
  be cut out of the wall before drawing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Union

from .model import (
    ArcEdge,
    ArcSegment,
    BoundaryRoom,
    CircleRoom,
    Corridor,
    LineEdge,
    LineSegment,
    PolygonRoom,
    RectRoom,
    Room,
    Vec2,
)

# Sides used to approximate a circular room as a polygon. High enough that
# the chord error is sub-pixel at normal map scales.
_CIRCLE_SAMPLES = 64


def circle_points(center: Vec2, radius: float, n: int = _CIRCLE_SAMPLES) -> list[Vec2]:
    """A circle sampled into `n` polygon vertices (counter-clockwise)."""
    cx, cy = center
    return [
        (cx + radius * math.cos(2 * math.pi * i / n),
         cy + radius * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]

EPS = 1e-6


@dataclass(frozen=True)
class LineWall:
    """A straight wall segment from `a` to `b`."""
    a: Vec2
    b: Vec2


@dataclass(frozen=True)
class ArcWall:
    """A circular-arc wall from `a` to `b` passing through `via`."""
    a: Vec2
    b: Vec2
    via: Vec2


Wall = Union[LineWall, ArcWall]


# ----- enumeration -----

def room_walls(room: Room) -> list[Wall]:
    """Closed boundary of a room as an ordered list of walls."""
    s = room.shape
    if isinstance(s, RectRoom):
        x, y = s.position
        w, h = s.width, s.height
        corners: list[Vec2] = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        return _close_line_polygon(corners)
    if isinstance(s, PolygonRoom):
        return _close_line_polygon(s.points)
    if isinstance(s, CircleRoom):
        return _close_line_polygon(circle_points(s.center, s.radius))
    if isinstance(s, BoundaryRoom):
        walls: list[Wall] = []
        cur = s.start
        for e in s.edges:
            if isinstance(e, LineEdge):
                walls.append(LineWall(cur, e.end))
            else:
                walls.append(ArcWall(cur, e.end, e.via))
            cur = e.end
        if _dist(cur, s.start) > EPS:
            walls.append(LineWall(cur, s.start))
        return walls
    raise TypeError(f"unknown room shape: {type(s).__name__}")


def _close_line_polygon(pts: list[Vec2]) -> list[Wall]:
    n = len(pts)
    return [LineWall(pts[i], pts[(i + 1) % n]) for i in range(n)]


# ----- low-level geometry -----

def _dist(a: Vec2, b: Vec2) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _cross_z(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    """Z-component of (b-a) x (c-a) — twice the signed area of triangle abc."""
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


# ----- shared-edge detection -----

def overlap_segment(w1: LineWall, w2: LineWall) -> tuple[Vec2, Vec2] | None:
    """If two line walls overlap collinearly, return the overlap subsegment.

    Returns None if they aren't collinear, or if they only touch at a
    single point.
    """
    ax, ay = w1.a
    bx, by = w1.b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < EPS * EPS:
        return None

    # Collinearity test — both endpoints of w2 must lie on the infinite
    # line through w1. The cross is ~ 2 * signed_area = L * perp_dist.
    L = L2 ** 0.5
    tol = max(L, 1.0) * 1e-6
    if abs(_cross_z(ax, ay, bx, by, *w2.a)) > tol:
        return None
    if abs(_cross_z(ax, ay, bx, by, *w2.b)) > tol:
        return None

    def t_of(p: Vec2) -> float:
        return ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2

    tb_lo, tb_hi = sorted((t_of(w2.a), t_of(w2.b)))
    lo = max(0.0, tb_lo)
    hi = min(1.0, tb_hi)
    # Require more than a single-point touch.
    if (hi - lo) * L < EPS:
        return None

    def point_at(t: float) -> Vec2:
        return (ax + t * dx, ay + t * dy)

    return point_at(lo), point_at(hi)


def shared_segments(
    rooms: dict[str, Room],
) -> list[tuple[str, str, tuple[Vec2, Vec2]]]:
    """Pairs of rooms with their shared-wall subsegments."""
    walls_by_room: list[tuple[str, list[LineWall]]] = []
    for name, r in rooms.items():
        walls_by_room.append(
            (name, [w for w in room_walls(r) if isinstance(w, LineWall)])
        )
    out: list[tuple[str, str, tuple[Vec2, Vec2]]] = []
    n = len(walls_by_room)
    for i in range(n):
        na, wa = walls_by_room[i]
        for j in range(i + 1, n):
            nb, wb = walls_by_room[j]
            for ea in wa:
                for eb in wb:
                    seg = overlap_segment(ea, eb)
                    if seg is not None:
                        out.append((na, nb, seg))
    return out


# ----- projection / door cutting -----

def project_onto_wall(p: Vec2, w: LineWall) -> tuple[Vec2, float, float]:
    """Project `p` onto line wall `w`.

    Returns `(projected_point, t, dist)` where `t` is clamped to [0, 1]
    along the wall and `dist` is the perpendicular distance from `p` to
    the projected point.
    """
    ax, ay = w.a
    bx, by = w.b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < EPS * EPS:
        return w.a, 0.0, _dist(p, w.a)
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2
    t = max(0.0, min(1.0, t))
    proj = (ax + t * dx, ay + t * dy)
    return proj, t, _dist(p, proj)


def cut_wall(w: LineWall, t_lo: float, t_hi: float) -> list[LineWall]:
    """Remove the [t_lo, t_hi] subsegment from `w`, returning what's left.

    `t_lo` and `t_hi` are along-wall parameters in [0, 1].
    """
    t_lo = max(0.0, t_lo)
    t_hi = min(1.0, t_hi)
    if t_hi <= t_lo + EPS:
        return [w]
    ax, ay = w.a
    bx, by = w.b
    dx, dy = bx - ax, by - ay
    pieces: list[LineWall] = []
    if t_lo > EPS:
        pieces.append(LineWall(w.a, (ax + t_lo * dx, ay + t_lo * dy)))
    if t_hi < 1.0 - EPS:
        pieces.append(LineWall((ax + t_hi * dx, ay + t_hi * dy), w.b))
    return pieces


def wall_length(w: LineWall) -> float:
    return _dist(w.a, w.b)


# ----- interior-overlap detection (validation) -----
#
# Distinct from `shared_segments`: two adjacent rooms are *meant* to share
# a wall, and that is fine. What we flag here is two areas whose interiors
# genuinely intersect — a sign the author placed one space on top of
# another by mistake. Arcs are sampled into short chords; this is a
# warning-grade heuristic, not exact area arithmetic.

_ARC_SAMPLES = 12


def _arc_points(a: Vec2, b: Vec2, via: Vec2, n: int = _ARC_SAMPLES) -> list[Vec2]:
    """Sample an arc through a→via→b into `n` chord points (excluding `a`)."""
    ax, ay = a
    bx, by = b
    vx, vy = via
    # Circle through three points (perpendicular-bisector intersection).
    d = 2 * (ax * (by - vy) + bx * (vy - ay) + vx * (ay - by))
    if abs(d) < EPS:  # collinear → treat as a straight chord
        return [b]
    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    v2 = vx * vx + vy * vy
    cx = (a2 * (by - vy) + b2 * (vy - ay) + v2 * (ay - by)) / d
    cy = (a2 * (vx - bx) + b2 * (ax - vx) + v2 * (bx - ax)) / d
    r = _dist((cx, cy), a)
    a0 = math.atan2(ay - cy, ax - cx)
    a1 = math.atan2(by - cy, bx - cx)
    am = math.atan2(vy - cy, vx - cx)

    def norm(x: float) -> float:
        while x - a0 > math.pi:
            x -= 2 * math.pi
        while x - a0 < -math.pi:
            x += 2 * math.pi
        return x

    a1n, amn = norm(a1), norm(am)
    # Ensure the sweep direction passes through the via point.
    if not (min(a0, a1n) <= amn <= max(a0, a1n)):
        a1n += 2 * math.pi if a1n < a0 else -2 * math.pi
    return [
        (cx + r * math.cos(a0 + (a1n - a0) * i / n),
         cy + r * math.sin(a0 + (a1n - a0) * i / n))
        for i in range(1, n + 1)
    ]


def room_polygon(room: Room) -> list[Vec2]:
    """A room's outline as a flat list of polygon vertices (arcs sampled)."""
    s = room.shape
    if isinstance(s, RectRoom):
        x, y = s.position
        w, h = s.width, s.height
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    if isinstance(s, PolygonRoom):
        return list(s.points)
    if isinstance(s, CircleRoom):
        return circle_points(s.center, s.radius)
    if isinstance(s, BoundaryRoom):
        pts: list[Vec2] = [s.start]
        cur = s.start
        for e in s.edges:
            if isinstance(e, ArcEdge):
                pts.extend(_arc_points(cur, e.end, e.via))
            else:
                pts.append(e.end)
            cur = e.end
        return pts
    raise TypeError(f"unknown room shape: {type(s).__name__}")


def corridor_polygons(corr: Corridor) -> list[list[Vec2]]:
    """A corridor as a list of width-buffered polygons, one per segment.

    Each straight segment becomes a rectangle of the corridor's width;
    each arc becomes a buffered band sampled into a polygon.
    """
    half = corr.width / 2.0
    polys: list[list[Vec2]] = []

    def buffer_chord(a: Vec2, b: Vec2) -> list[Vec2] | None:
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < EPS:
            return None
        nx, ny = -dy / L * half, dx / L * half
        return [
            (a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
            (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny),
        ]

    for seg in corr.segments:
        if isinstance(seg, LineSegment):
            p = buffer_chord(seg.start, seg.end)
            if p:
                polys.append(p)
        elif isinstance(seg, ArcSegment):
            # Sample the arc centerline, buffer each chord.
            a0, a1 = seg.from_angle, seg.to_angle
            if seg.sweep == "cw" and a1 > a0:
                a1 -= 2 * math.pi
            if seg.sweep == "ccw" and a1 < a0:
                a1 += 2 * math.pi
            cx, cy = seg.center
            pts = [
                (cx + seg.radius * math.cos(a0 + (a1 - a0) * i / _ARC_SAMPLES),
                 cy + seg.radius * math.sin(a0 + (a1 - a0) * i / _ARC_SAMPLES))
                for i in range(_ARC_SAMPLES + 1)
            ]
            for a, b in zip(pts, pts[1:]):
                p = buffer_chord(a, b)
                if p:
                    polys.append(p)
    return polys


def _orient(a: Vec2, b: Vec2, c: Vec2) -> float:
    return _cross_z(a[0], a[1], b[0], b[1], c[0], c[1])


def _proper_segments_intersect(p1: Vec2, p2: Vec2, p3: Vec2, p4: Vec2) -> bool:
    """True if segments p1p2 and p3p4 cross at a single interior point.

    Collinear overlaps and shared/endpoint touches return False, so two
    rooms sharing a wall are not treated as intersecting.
    """
    d1 = _orient(p3, p4, p1)
    d2 = _orient(p3, p4, p2)
    d3 = _orient(p1, p2, p3)
    d4 = _orient(p1, p2, p4)
    if min(abs(d1), abs(d2), abs(d3), abs(d4)) < EPS:
        return False  # some point is collinear → a touch, not a crossing
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _point_strictly_inside(pt: Vec2, poly: list[Vec2]) -> bool:
    """Ray-cast point-in-polygon, returning False for points on the boundary."""
    n = len(poly)
    if n < 3:
        return False
    # On-boundary → not strictly inside.
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if abs(_orient(a, b, pt)) < EPS:
            # collinear with edge; inside the segment's bounding box?
            if (min(a[0], b[0]) - EPS <= pt[0] <= max(a[0], b[0]) + EPS
                    and min(a[1], b[1]) - EPS <= pt[1] <= max(a[1], b[1]) + EPS):
                return False
    inside = False
    x, y = pt
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        if (ay > y) != (by > y):
            xc = ax + (y - ay) * (bx - ax) / (by - ay)
            if x < xc:
                inside = not inside
    return inside


def _centroid(poly: list[Vec2]) -> Vec2:
    n = len(poly)
    return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)


def polygons_overlap(a: list[Vec2], b: list[Vec2]) -> bool:
    """True if two simple polygons' interiors intersect (not just touch)."""
    if len(a) < 3 or len(b) < 3:
        return False
    na, nb = len(a), len(b)
    for i in range(na):
        a1, a2 = a[i], a[(i + 1) % na]
        for j in range(nb):
            b1, b2 = b[j], b[(j + 1) % nb]
            if _proper_segments_intersect(a1, a2, b1, b2):
                return True
    # Containment (one fully inside the other, no edge crossings).
    if any(_point_strictly_inside(p, b) for p in a):
        return True
    if any(_point_strictly_inside(p, a) for p in b):
        return True
    # Identical / near-identical polygons: edges only touch, vertices sit on
    # the boundary — fall back to a centroid test.
    if _point_strictly_inside(_centroid(a), b) or _point_strictly_inside(
        _centroid(b), a
    ):
        return True
    return False


def overlap_area(a: list[Vec2], b: list[Vec2], step: float = 0.2) -> float:
    """Approximate the intersection area of two polygons by point sampling.

    Samples a regular grid over the polygons' overlapping bounding box and
    counts cells whose centre is strictly inside both. Accurate to roughly
    `step**2`, which is ample for a warning-grade threshold; it handles
    concave room outlines that exact convex clipping would not.
    """
    if len(a) < 3 or len(b) < 3:
        return 0.0
    ax0 = max(min(p[0] for p in a), min(p[0] for p in b))
    ay0 = max(min(p[1] for p in a), min(p[1] for p in b))
    ax1 = min(max(p[0] for p in a), max(p[0] for p in b))
    ay1 = min(max(p[1] for p in a), max(p[1] for p in b))
    if ax0 >= ax1 or ay0 >= ay1:
        return 0.0
    cell = step * step
    total = 0.0
    y = ay0 + step / 2
    while y < ay1:
        x = ax0 + step / 2
        while x < ax1:
            if _point_strictly_inside((x, y), a) and _point_strictly_inside((x, y), b):
                total += cell
            x += step
        y += step
    return total


@dataclass(frozen=True)
class Area:
    """A labelled set of polygons (a room = 1, a corridor = many)."""
    label: str
    polygons: list[list[Vec2]]


def find_overlapping_areas(
    areas: list[Area], min_area: float = 0.0
) -> list[tuple[str, str, float]]:
    """Return `(label_a, label_b, area)` for every pair whose areas overlap
    by at least `min_area` square units. Each unordered pair is compared
    once; an area is never compared with itself. The reported area is the
    largest single polygon-pair overlap between the two (corridors carry
    several polygons)."""
    out: list[tuple[str, str, float]] = []
    n = len(areas)
    for i in range(n):
        for j in range(i + 1, n):
            best = 0.0
            hit = False
            for pa in areas[i].polygons:
                for pb in areas[j].polygons:
                    if not polygons_overlap(pa, pb):
                        continue
                    hit = True
                    if min_area <= 0.0:
                        break
                    best = max(best, overlap_area(pa, pb))
                if hit and min_area <= 0.0:
                    break
            if hit and best >= min_area:
                out.append((areas[i].label, areas[j].label, best))
    return out
