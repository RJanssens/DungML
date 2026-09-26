"""Auto-placement for room / area labels that give no `at` or `align`.

The label's box has to fit inside the room and stay clear of the room's
features; a label too long for the room wraps onto two lines, then shrinks
(to 70% at most). The first layout that fits wins, tried in this order:
one line, two lines, then the same at 85% and 70% size (and, in a room too
cramped even for that, smaller still, down to 50%). For each layout the
room's centre is tried first, then its pole of inaccessibility, then a grid
of points nearest that pole — so an unobstructed rectangular room keeps its
label dead centre, exactly as before.

Text is measured by estimate (no font metrics in a pure renderer): an
average glyph advance of CHAR_W em, generous for the italic serif labels
use, so a label that "fits" does.

Pure geometry over shapely; world coordinates (the caller flips y).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

from shapely.geometry import Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polylabel
from shapely.prepared import prep

from .model import (
    CircleShape,
    FeatureDef,
    FeatureInstance,
    GlyphCircle,
    GlyphLine,
    GlyphPath,
    GlyphPolygon,
    GlyphPolyline,
    GlyphRect,
    PolygonShape,
    RectShape,
)

CHAR_W = 0.52  # average glyph advance, in em
LINE_H = 1.15  # line height, in em
SCALES = (1.0, 0.85, 0.7)
# Past the normal steps, a cramped room shrinks the label further rather
# than let it spill over the walls — down to half size.
CRAMPED_SCALES = (0.65, 0.6, 0.55, 0.5)
INSET = 0.25  # keep the box this far inside the walls
CLEARANCE = 0.1  # and this far off any obstacle


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    size: float  # font size, world units
    lines: tuple[str, ...]


def text_box(lines, size: float) -> tuple[float, float]:
    """(width, height) the lines take up at `size`."""
    lines = list(lines)
    return (
        max((len(s) for s in lines), default=0) * CHAR_W * size,
        len(lines) * LINE_H * size,
    )


def _two_lines(text: str) -> Optional[tuple[str, str]]:
    """Split at the space nearest the middle, or None for a single word."""
    spaces = [i for i, c in enumerate(text) if c == " "]
    if not spaces:
        return None
    mid = len(text) / 2
    cut = min(spaces, key=lambda i: (abs(i - mid), i))
    return text[:cut], text[cut + 1:]


def _layouts(text: str, size: float, scales=SCALES):
    split = _two_lines(text)
    for scale in scales:
        yield size * scale, (text,)
        if split is not None:
            yield size * scale, split


def _grid(area: BaseGeometry, near: Point) -> list[tuple[float, float]]:
    minx, miny, maxx, maxy = area.bounds
    step = max(0.25, max(maxx - minx, maxy - miny) / 24)
    pts = [
        (minx + i * step, miny + j * step)
        for i in range(int((maxx - minx) / step) + 1)
        for j in range(int((maxy - miny) / step) + 1)
    ]
    return sorted(pts, key=lambda p: (math.dist(p, (near.x, near.y)), p))


def place_label(
    room: BaseGeometry,
    obstacles: Optional[BaseGeometry],
    text: str,
    size: float,
) -> Placement:
    """Where (and how) to draw `text` inside `room`, clear of `obstacles`."""
    area = room.buffer(-INSET)
    if area.is_empty:
        area = room
    blocked = obstacles.buffer(CLEARANCE) if obstacles is not None and not obstacles.is_empty else None
    inside = prep(area)
    clash = prep(blocked) if blocked is not None else None

    centre = room.centroid
    pole = polylabel(area if area.geom_type == "Polygon" else room, tolerance=0.05)
    first = [(centre.x, centre.y), (pole.x, pole.y)]

    def fits(p: tuple[float, float], lines, s: float) -> bool:
        w, h = text_box(lines, s)
        r = box(p[0] - w / 2, p[1] - h / 2, p[0] + w / 2, p[1] + h / 2)
        return inside.contains(r) and (clash is None or not clash.intersects(r))

    grid: Optional[list[tuple[float, float]]] = None
    layouts = list(_layouts(text, size)) + list(_layouts(text, size, CRAMPED_SCALES))
    for s, lines in layouts:
        for p in first:
            if fits(p, lines, s):
                return Placement(p[0], p[1], s, tuple(lines))
        if grid is None:
            grid = _grid(area, pole)
        for p in grid:
            if fits(p, lines, s):
                return Placement(p[0], p[1], s, tuple(lines))

    # Nothing fits even at half size: the smallest layout at the room's pole.
    s, lines = layouts[-1]
    return Placement(pole.x, pole.y, s, tuple(lines))


# ----- what a feature occupies -----

_NUM = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _local_extent(fd: Optional[FeatureDef]) -> float:
    """Radius (local units) that encloses a feature's drawing."""
    if fd is None:
        return 0.35  # the renderer's placeholder square
    r = 0.0
    if fd.shape is not None:
        s = fd.shape
        if isinstance(s, CircleShape):
            r = s.radius
        elif isinstance(s, RectShape):
            r = math.hypot(s.width / 2, s.height / 2)
        elif isinstance(s, PolygonShape):
            r = max((math.hypot(x, y) for x, y in s.points), default=0.0)
    for ov in fd.overlays:
        ox, oy = ov.offset
        r = max(r, math.hypot(ox, oy))
    for g in fd.glyph:
        if isinstance(g, GlyphCircle):
            r = max(r, math.hypot(g.cx, g.cy) + g.r)
        elif isinstance(g, GlyphRect):
            r = max(r, *(math.hypot(x, y) for x in (g.x, g.x + g.width)
                         for y in (g.y, g.y + g.height)))
        elif isinstance(g, GlyphLine):
            r = max(r, math.hypot(g.x1, g.y1), math.hypot(g.x2, g.y2))
        elif isinstance(g, (GlyphPolygon, GlyphPolyline)):
            r = max(r, *(math.hypot(x, y) for x, y in g.points), 0.0)
        elif isinstance(g, GlyphPath):
            nums = [float(n) for n in _NUM.findall(g.d)]
            r = max(r, *(math.hypot(x, y) for x, y in zip(nums[::2], nums[1::2])), 0.0)
    return r or 0.35


def feature_footprint(fd: Optional[FeatureDef], fi: FeatureInstance) -> BaseGeometry:
    """A disc covering a placed feature (its drawing, scaled, any rotation)."""
    scale = max(abs(fi.scale), abs(fi.scale_y if fi.scale_y is not None else fi.scale))
    return Point(fi.position).buffer(_local_extent(fd) * scale, quad_segs=8)
