"""classic-bw — black-and-white technical-drawing style renderer.

Outputs SVG with the map's coordinate units as the viewBox unit. The
SVG width/height attributes scale up by the grid's `cell_px`, so the
on-screen size is `cell_px` per world unit while the geometry stays in
world coordinates throughout.
"""
from __future__ import annotations

import math
from html import escape
from typing import Iterable

from ..geometry import (
    ArcWall,
    LineWall,
    Wall,
    corridor_polygons,
    cut_wall,
    project_onto_wall,
    room_walls,
    wall_length,
)
from ..model import (
    ArcSegment,
    CircleShape,
    Corridor,
    Door,
    DungeonMap,
    FeatureDef,
    FeatureInstance,
    GlyphCircle,
    GlyphLine,
    GlyphPath,
    GlyphPolygon,
    GlyphPolyline,
    GlyphRect,
    Layer,
    LineFeature,
    LineSegment,
    Area,
    Marker,
    TextAnnotation,
    Overlay,
    PolygonShape,
    RectShape,
    Room,
    Slice,
    Vec2,
    Window,
)
from . import Renderer, register

# Stroke / sizing constants, all in world units.
WALL_STROKE = 0.18
CORRIDOR_STROKE = 0.10
WINDOW_STROKE = 0.06
DOOR_STROKE = 0.10
FEATURE_STROKE = 0.06
# `line_style trail` — x-marks spaced along the wall (a footpath / route).
TRAIL_SPACING = 0.55  # world-unit gap between x-marks

# Built-in palette for `area` terrain kinds: kind -> (fill, outline).
# `fill` is a background token resolved through `_resolve_bg` (so "water"
# maps to the built-in texture; the rest are CSS colours). Unknown kinds
# fall back to `_default`. An area's explicit `background` overrides `fill`.
AREA_KINDS: dict[str, tuple[str, str]] = {
    "water": ("water", "#3f6d86"),  # built-in water texture
    "lava": ("#e2521d", "#7a2708"),
    "pit": ("#1b1b1b", "#000000"),
    "chasm": ("#0c0c0c", "#000000"),
    "mud": ("#6b5234", "#3f2f1c"),
    "acid": ("#7fcf3f", "#3f6f1f"),
    "ice": ("#cfe8f2", "#7fa8bd"),
    "blood": ("#7c1414", "#3f0a0a"),
    "slime": ("#4fae6a", "#256b39"),
    "swamp": ("#5d6b3a", "#374122"),
    "_default": ("#9fb0bd", "#5b6b78"),
}
AREA_OUTLINE_STROKE = 0.12
TRAIL_MARK = 0.12  # half-size of each x
TRAIL_STROKE = 0.05  # x-mark stroke width
# `line_feature` styling (bars / curtain / barred).
LINE_FEATURE_STROKE = 0.07
CURTAIN_AMP = 0.13  # wave amplitude (perpendicular to the path)
CURTAIN_WAVELEN = 0.5  # wave length along the path
BARRED_SPACING = 0.5  # gap between `+` marks
BARRED_MARK = 0.12  # half-size of each `+`
LABEL_BASE_SIZE = 0.9
LABEL_INSET = 0.5  # world-unit padding from the room bbox for relative-aligned labels
DOOR_WIDTH_DEFAULT = 1.0
WINDOW_INSET = 0.06  # how far the parallel window lines sit from the wall
LEGEND_HEIGHT = 4.0  # world-unit thickness of the legend strip below the map

# Marker tag → CSS colour. Any tag string not in this table is passed
# through verbatim as a CSS value, so authors can write either
# `tag party` or `tag "#ff8800"`.
MARKER_PALETTE: dict[str, str] = {
    "party":   "#2c7be5",
    "ally":    "#2db469",
    "npc":     "#f5a623",
    "enemy":   "#c43232",
    "boss":    "#8b1a8a",
    "neutral": "#6b6b6b",
    "unknown": "#999999",
}
MARKER_DEFAULT_TAG = "neutral"


# ----- background textures -----
#
# Each entry is an SVG <pattern> definition keyed by name. A map, room, or
# corridor that names one of these (instead of a color) gets
# `url(#dungml-tx-NAME)` as its fill, and the renderer injects the pattern
# into <defs> on demand. Pattern coordinates use `userSpaceOnUse` so the
# tile scale matches world units independent of cell_px.
_TEXTURES: dict[str, str] = {
    "stone": (
        '<pattern id="dungml-tx-stone" patternUnits="userSpaceOnUse" '
        'width="2" height="2">'
        '<rect width="2" height="2" fill="#5e5e5e"/>'
        '<circle cx="0.3" cy="0.4" r="0.12" fill="#4a4a4a"/>'
        '<circle cx="1.2" cy="0.9" r="0.10" fill="#737373"/>'
        '<circle cx="0.8" cy="1.6" r="0.08" fill="#4a4a4a"/>'
        '<circle cx="1.7" cy="1.4" r="0.07" fill="#737373"/>'
        '</pattern>'
    ),
    "parchment": (
        '<pattern id="dungml-tx-parchment" patternUnits="userSpaceOnUse" '
        'width="2.4" height="2.4">'
        '<rect width="2.4" height="2.4" fill="#f3e6c4"/>'
        '<circle cx="0.4" cy="0.5" r="0.05" fill="#d6c08a"/>'
        '<circle cx="1.6" cy="1.2" r="0.04" fill="#d6c08a"/>'
        '<circle cx="2.0" cy="2.1" r="0.05" fill="#bea465"/>'
        '<path d="M 0 1.3 Q 1.2 1.1 2.4 1.4" stroke="#d6c08a" '
        'stroke-width="0.02" fill="none"/>'
        '</pattern>'
    ),
    "water": (
        '<pattern id="dungml-tx-water" patternUnits="userSpaceOnUse" '
        'width="2.4" height="1.2">'
        '<rect width="2.4" height="1.2" fill="#4f7c8a"/>'
        '<path d="M 0 0.55 Q 0.6 0.3 1.2 0.55 T 2.4 0.55" '
        'stroke="#86b0bd" stroke-width="0.05" fill="none"/>'
        '<path d="M 0 0.95 Q 0.6 0.7 1.2 0.95 T 2.4 0.95" '
        'stroke="#86b0bd" stroke-width="0.04" fill="none"/>'
        '</pattern>'
    ),
    "grass": (
        '<pattern id="dungml-tx-grass" patternUnits="userSpaceOnUse" '
        'width="2" height="2">'
        '<rect width="2" height="2" fill="#7ea763"/>'
        '<line x1="0.3" y1="0.5" x2="0.3" y2="0.2" stroke="#4e6a3a" '
        'stroke-width="0.05"/>'
        '<line x1="0.6" y1="1.4" x2="0.6" y2="1.1" stroke="#4e6a3a" '
        'stroke-width="0.05"/>'
        '<line x1="1.4" y1="0.9" x2="1.4" y2="0.6" stroke="#4e6a3a" '
        'stroke-width="0.05"/>'
        '<line x1="1.7" y1="1.7" x2="1.7" y2="1.4" stroke="#4e6a3a" '
        'stroke-width="0.05"/>'
        '</pattern>'
    ),
    "dirt": (
        '<pattern id="dungml-tx-dirt" patternUnits="userSpaceOnUse" '
        'width="2" height="2">'
        '<rect width="2" height="2" fill="#9b7a4f"/>'
        '<circle cx="0.4" cy="0.5" r="0.07" fill="#7a5d36"/>'
        '<circle cx="1.2" cy="1.1" r="0.09" fill="#bb946e"/>'
        '<circle cx="1.7" cy="0.4" r="0.05" fill="#7a5d36"/>'
        '<circle cx="0.6" cy="1.6" r="0.06" fill="#7a5d36"/>'
        '</pattern>'
    ),
    "forest": (
        '<pattern id="dungml-tx-forest" patternUnits="userSpaceOnUse" '
        'width="2.4" height="2.4">'
        '<rect width="2.4" height="2.4" fill="#516b3b"/>'
        '<circle cx="0.5" cy="0.6" r="0.22" fill="#3d5429"/>'
        '<circle cx="1.7" cy="1.0" r="0.18" fill="#3d5429"/>'
        '<circle cx="0.9" cy="1.8" r="0.20" fill="#3d5429"/>'
        '<circle cx="2.1" cy="2.0" r="0.16" fill="#3d5429"/>'
        '</pattern>'
    ),
}


def _resolve_fill(value: str | None) -> tuple[str | None, str | None]:
    """Resolve a `background` string to (svg_fill, texture_name_to_register).

    Returns (None, None) when the value is empty so callers can fall through
    to their own defaults. Known texture ids map to a pattern reference and
    flag that pattern for registration in <defs>. Anything else (hex,
    rgb(), named CSS color) is passed through verbatim.
    """
    if not value:
        return None, None
    if value in _TEXTURES:
        return f"url(#dungml-tx-{value})", value
    return value, None


@register("classic-bw")
class ClassicBW(Renderer):
    """Technical-drawing style B/W renderer."""

    def render(self, dmap: DungeonMap) -> str:
        ctx = self._context_for(dmap)
        return ctx.render()

    def _context_for(self, dmap: DungeonMap) -> "_RenderContext":
        return _RenderContext(dmap)


# Aliases that share the same look — also registered.
@register("floorplan")
class Floorplan(ClassicBW):
    """Alias for classic-bw, used for building-style maps."""


@register("hatched")
class Hatched(ClassicBW):
    """Hatched-fill style — diagonal lines instead of a flat floor fill.

    Evokes architectural section drawings. Walls, doors, features, and
    labels render the same as classic-bw; only the floor pattern changes.
    """

    def _context_for(self, dmap: DungeonMap) -> "_RenderContext":
        return _HatchedContext(dmap)


# ----- internal helpers -----

class _RenderContext:
    def __init__(self, dmap: DungeonMap) -> None:
        self.dmap = dmap
        self.cfg = dmap.map.grid
        self.W = self.cfg.bounds_w
        self.H = self.cfg.bounds_h
        self.flip_y = self.cfg.origin == "bottom-left"
        # All rooms from top-level + visible layers, by name (top-level
        # take precedence if a layer reuses the same name).
        self.all_rooms: dict[str, Room] = dict(dmap.rooms)
        for layer in dmap.layers:
            if layer.hidden:
                continue
            for r in layer.rooms:
                self.all_rooms.setdefault(r.name, r)
        # Sequential numbering in source order (dict preserves insertion).
        self.room_numbers: dict[str, int] = {
            name: i + 1 for i, name in enumerate(self.all_rooms)
        }
        # Textures actually referenced from this map (one pattern def per
        # texture name). Built up by `_resolve_bg`; we pre-pass over
        # map/rooms/corridors so the set is populated before <defs> emit.
        self._textures_used: set[str] = set()
        for bg in self._all_background_values():
            self._resolve_bg(bg)

    def _all_background_values(self) -> list[str | None]:
        """All `background` strings declared anywhere in this dmap."""
        out: list[str | None] = [self.dmap.map.background]
        for r in self.all_rooms.values():
            out.append(r.background)
        for c in self.dmap.corridors.values():
            out.append(c.background)
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            for c in layer.corridors:
                out.append(c.background)
        # Areas: both an explicit `background` and the kind's palette fill
        # (e.g. kind water → the "water" texture) need registering up front.
        for a in self._all_areas():
            out.append(a.background)
            out.append(AREA_KINDS.get(a.kind, AREA_KINDS["_default"])[0])
        return out

    # --- background fill resolution ---

    def _resolve_bg(self, value: str | None) -> str | None:
        """Resolve a `background` string to an SVG fill, registering any
        texture pattern that gets referenced. Returns None when no value was
        set — callers fall back to their own defaults.
        """
        fill, texture = _resolve_fill(value)
        if texture is not None:
            self._textures_used.add(texture)
        return fill

    # --- coordinate helpers ---

    def y(self, v: float) -> float:
        return (self.H - v) if self.flip_y else v

    def pt(self, p: Vec2) -> Vec2:
        return (p[0], self.y(p[1]))

    # --- top-level ---

    def render(self) -> str:
        cell = self.cfg.cell_px
        legend_h = LEGEND_HEIGHT if self.dmap.map.legend else 0.0
        total_h = self.H + legend_h
        w_px = self.W * cell
        h_px = total_h * cell
        title = escape(self.dmap.map.name)
        parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_n(self.W)} {_n(total_h)}" '
            f'width="{_n(w_px)}" height="{_n(h_px)}" '
            f'data-name="{title}" '
            # Map metadata for the web editor's drawing layer: the map area is
            # the [0, map-h] band of the viewBox (the legend, if any, sits
            # below it), and `data-origin` tells it whether world-y is flipped.
            f'data-map-w="{_n(self.W)}" data-map-h="{_n(self.H)}" '
            f'data-origin="{escape(self.cfg.origin)}">',
            self._defs(),
            f'<rect class="bg" x="0" y="0" width="{_n(self.W)}" '
            f'height="{_n(total_h)}" fill="{self._bg_fill()}"/>',
        ]

        # Optional layer drawn before room floors — used by the hatched
        # renderer for its halo of hatching around explorable space.
        pre = self._pre_rooms_layer()
        if pre:
            parts.append(pre)

        # Doors + windows aggregated across map and visible layers.
        doors = list(self.dmap.doors)
        windows = list(self.dmap.windows)
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            doors.extend(layer.doors)
            windows.extend(layer.windows)

        # Rooms (floor fills, then walls with door/window gaps cut).
        parts.append('<g class="rooms">')
        for r in self.all_rooms.values():
            parts.append(self._room_floor(r))
        parts.append("</g>")

        # Per-room grid overlays (drawn after floors so they sit above the
        # floor fill but below walls / features / labels).
        grid_overlays = [
            self._room_grid_overlay(r)
            for r in self.all_rooms.values()
            if r.grid is not None and r.grid > 0
        ]
        if any(grid_overlays):
            parts.append('<g class="room-grids">')
            parts.extend(grid_overlays)
            parts.append("</g>")

        # Global cell grid inside rooms — under the walls (drawn next).
        if self.dmap.map.cell_grid:
            room_grid = self._cell_grid_rooms()
            if room_grid:
                parts.append(room_grid)

        # Decorative terrain areas (water / lava / pits). Drawn above room
        # floors but below walls / corridors / features / labels so they read
        # as ground cover.
        areas = self._all_areas()
        if areas:
            parts.append('<g class="areas">')
            for a in areas:
                parts.append(self._area(a))
            parts.append("</g>")

        parts.append('<g class="walls">')
        for r in self.all_rooms.values():
            parts.append(self._room_walls(r, doors, windows))
        parts.append("</g>")

        # Corridors.
        all_corridors: list[Corridor] = list(self.dmap.corridors.values())
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            all_corridors.extend(layer.corridors)
        if all_corridors:
            parts.append('<g class="corridors">')
            for c in all_corridors:
                parts.append(self._corridor(c))
            parts.append("</g>")

        # Global cell grid inside corridors. The clip is the corridor floor
        # band (walls sit outside it), so this sits over the floor without
        # crossing the corridor walls.
        if self.dmap.map.cell_grid:
            corr_grid = self._cell_grid_corridors(all_corridors)
            if corr_grid:
                parts.append(corr_grid)

        # Cross-slices (rivers, ravines, splits). Drawn after corridors so
        # they overlay any corridor / room that happens to cross them, but
        # before doors/windows/features so bridges and other crossings sit
        # cleanly on top.
        all_slices: list[Slice] = list(self.dmap.slices.values())
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            all_slices.extend(layer.slices)
        if all_slices:
            parts.append('<g class="slices">')
            for s in all_slices:
                parts.append(self._slice(s))
            parts.append("</g>")

        # Line features (bars / curtains / barred enclosures).
        line_features = self._all_line_features()
        if line_features:
            parts.append('<g class="line-features">')
            for lf in line_features:
                parts.append(self._line_feature(lf))
            parts.append("</g>")

        # Doors.
        if doors:
            parts.append('<g class="doors">')
            for d in doors:
                parts.append(self._door(d))
            parts.append("</g>")

        # Windows.
        if windows:
            parts.append('<g class="windows">')
            for w in windows:
                parts.append(self._window(w))
            parts.append("</g>")

        # Features (room-attached + top-level + visible layer).
        parts.append('<g class="features">')
        for r in self.all_rooms.values():
            for fi in r.features:
                parts.append(self._feature(fi))
        for fi in self.dmap.features:
            parts.append(self._feature(fi))
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            for fi in layer.features:
                parts.append(self._feature(fi))
        parts.append("</g>")

        # Optional map-wide grid overlay (graph-paper style). Drawn after
        # all map content but before labels so labels stay readable.
        go_spacing, go_color = self._grid_overlay()
        if go_spacing and go_spacing > 0:
            parts.append(self._map_grid_overlay(go_spacing, go_color))

        # Markers (top-level + visible layer) — placed between features
        # and labels so they overlay furniture but room labels stay
        # readable on top of them.
        all_markers: list[Marker] = list(self.dmap.markers)
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            all_markers.extend(layer.markers)
        if all_markers:
            parts.append('<g class="markers">')
            for m in all_markers:
                parts.append(self._marker(m))
            parts.append("</g>")

        # Party start marker (where the PCs begin when the map loads).
        if self.dmap.map.party_start is not None:
            parts.append(self._party_start(self.dmap.map.party_start))

        # Labels last so they sit on top.
        parts.append('<g class="labels">')
        for r in self.all_rooms.values():
            if r.label is not None:
                parts.append(self._room_label(r))
        for s in all_slices:
            if s.label is not None:
                parts.append(self._slice_label(s))
        if self.dmap.map.title is not None:
            parts.append(self._map_title())
        all_texts: list[TextAnnotation] = list(self.dmap.texts)
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            all_texts.extend(layer.texts)
        for ta in all_texts:
            parts.append(self._text_annotation(ta))
        parts.append("</g>")

        # Legend strip below the map (if requested).
        if self.dmap.map.legend:
            parts.append(self._legend_strip())

        parts.append("</svg>")
        return "\n".join(p for p in parts if p)

    # --- defs (stylesheet + optional <defs>) ---

    def _defs(self) -> str:
        # Order: textures (patterns) → line-style filter → subclass extras →
        # global stylesheet. Filters and patterns each live in their own
        # <defs> wrapper so they can be inspected independently.
        organic = self._line_style_defs_block()
        organic_block = f"<defs>{organic}</defs>" if organic else ""
        return (
            self._texture_defs_block()
            + organic_block
            + self._extra_defs_block()
            + self._style_block()
        )

    def _texture_defs_block(self) -> str:
        """Wrap every used texture pattern in a single <defs>."""
        if not self._textures_used:
            return ""
        patterns = "".join(_TEXTURES[name] for name in sorted(self._textures_used))
        return f"<defs>{patterns}</defs>"

    def _line_style_defs_block(self) -> str:
        """Inject the displacement filter used by organic-edged rooms/corridors.

        Only emitted when at least one room or corridor opts in. A single
        filter is reused across every organic element so the wobble is
        consistent — and so we don't pay the cost when nothing uses it.
        """
        amounts = self._organic_amounts()
        if not amounts:
            return ""
        # feTurbulence + feDisplacementMap: low frequency = broad wobble,
        # scale = world-unit displacement magnitude. 0.25 (the default 1.0×
        # amount) is enough to feel hand-drawn without making the outline
        # ambiguous; `line_style organic N` scales it for more/less waviness.
        out: list[str] = []
        for fid, amount in sorted(amounts.items()):
            scale = 0.25 * amount
            # A generous region (bbox units) so the displacement isn't clipped
            # on thin shapes like corridors — clipping there left the long
            # sides straight but bowed the short ends into rounded caps. A
            # higher base frequency keeps the wobble fine, so ends read as
            # straight-but-rough rather than smoothly rounded.
            out.append(
                f'<filter id="{fid}" x="-50%" y="-50%" '
                'width="200%" height="200%">'
                '<feTurbulence type="fractalNoise" baseFrequency="0.9" '
                'numOctaves="2" seed="17" result="organic-noise"/>'
                '<feDisplacementMap in="SourceGraphic" in2="organic-noise" '
                f'scale="{_n(scale)}" xChannelSelector="R" yChannelSelector="G"/>'
                '</filter>'
            )
        return "".join(out)

    def _organic_id(self, amount: float | None) -> str:
        a = 1.0 if amount is None else amount
        if abs(a - 1.0) < 1e-9:
            return "dungml-fx-organic"
        return "dungml-fx-organic-" + ("%g" % a).replace("-", "m").replace(".", "_")

    def _organic_filter_attr(
        self, line_style: str | None, amount: float | None
    ) -> str:
        """` filter="..."` attribute for an organic-edged element (else "")."""
        if line_style != "organic":
            return ""
        return f' filter="url(#{self._organic_id(amount)})"'

    def _organic_amounts(self) -> dict[str, float]:
        """filter-id -> waviness amount for every organic room/corridor."""
        out: dict[str, float] = {}

        def add(ls: str | None, amt: float | None) -> None:
            if ls == "organic":
                out[self._organic_id(amt)] = 1.0 if amt is None else amt

        for r in self.all_rooms.values():
            add(r.line_style, r.line_style_amount)
        for c in self.dmap.corridors.values():
            add(c.line_style, c.line_style_amount)
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            for c in layer.corridors:
                add(c.line_style, c.line_style_amount)
        for a in self._all_areas():
            add(a.line_style, a.line_style_amount)
        return out

    def _all_areas(self) -> list[Area]:
        """Top-level areas plus those in visible layers."""
        areas: list[Area] = list(self.dmap.areas)
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            areas.extend(layer.areas)
        return areas

    def _style_block(self) -> str:
        # Corridor-wall / corridor-floor strokes are configured per-path
        # with inline stroke + stroke-width attributes; the classes here
        # only set fill, so they don't override those presentation
        # attributes via CSS specificity.
        return (
            "<style>"
            f".wall{{fill:none;stroke:#111;stroke-width:{_n(WALL_STROKE)};"
            "stroke-linecap:square;stroke-linejoin:miter}"
            # `line_style ruined` — dash-dot walls (a crumbled / ruined
            # structure). The descendant selector outranks `.wall` so it
            # overrides the cap and adds the dash pattern; round caps turn
            # the zero-ish dashes into dots.
            f".ruined .wall{{stroke-dasharray:{_n(WALL_STROKE * 3)},"
            f"{_n(WALL_STROKE * 1.8)},0.01,{_n(WALL_STROKE * 1.8)};"
            "stroke-linecap:round;stroke-linejoin:round}"
            # `line_style dotted` — round dots (a zero-length dash + round cap).
            f".dotted .wall{{stroke-dasharray:0.01,{_n(WALL_STROKE * 1.6)};"
            "stroke-linecap:round;stroke-linejoin:round}"
            # `line_style dashed` — even dashes.
            f".dashed .wall{{stroke-dasharray:{_n(WALL_STROKE * 3)},"
            f"{_n(WALL_STROKE * 2)};stroke-linecap:butt}}"
            # `line_style trail` — x-marks drawn along the wall (see below).
            f".trail-x{{fill:none;stroke:#111;stroke-width:{_n(TRAIL_STROKE)};"
            "stroke-linecap:round}"
            f".line-feature{{fill:none;stroke:#111;"
            f"stroke-width:{_n(LINE_FEATURE_STROKE)};stroke-linecap:round;"
            "stroke-linejoin:round}"
            f".floor{{fill:{self._floor_fill()};stroke:none}}"
            ".corridor-wall{fill:none}"
            ".corridor-floor{fill:none}"
            f".door{{fill:none;stroke:#111;stroke-width:{_n(DOOR_STROKE)};"
            "stroke-linecap:butt}"
            f".window{{fill:none;stroke:#111;stroke-width:{_n(WINDOW_STROKE)}}}"
            f".feature{{fill:#fff;stroke:#111;stroke-width:{_n(FEATURE_STROKE)}}}"
            ".feature-fill{fill:#111;stroke:none}"
            f".label{{font-family:Georgia,serif;font-style:italic;"
            f"fill:#111;"
            # text-anchor/dominant-baseline are set per-element so labels
            # with `align` can override the centered default.
            f"paint-order:stroke;stroke:{self._floor_fill()};"
            f"stroke-width:0.18;stroke-linejoin:round}}"
            # Default colour on the group so a per-grid `style="stroke:…"`
            # override (inline) wins; lines inherit the stroke.
            ".room-grid{stroke:#b8b3a3}.room-grid line{stroke-width:0.04;fill:none}"
            ".map-grid line{stroke:#9a937f;stroke-width:0.035;fill:none;"
            "opacity:0.55}"
            "</style>"
        )

    # ---- hooks for subclasses ----

    def _floor_fill(self) -> str:
        """CSS fill value used for room floors when no per-room override."""
        return "#fafafa"

    def _corridor_floor_fill(self) -> str:
        """CSS fill value used for corridor floors when no per-corridor override."""
        return "#fafafa"

    def _bg_default(self) -> str:
        """Subclass hook: default page background when map.background unset."""
        return "#ffffff"

    def _grid_overlay(self) -> tuple[float | None, str | None]:
        """Subclass hook: (spacing, color) for the graph-paper grid overlay.

        Defaults to whatever the map declared (`grid_overlay` / its color);
        styles like old-school blue override this to turn the grid on by
        default and tint it.
        """
        return self.dmap.map.grid_overlay, self.dmap.map.grid_overlay_color

    def _bg_fill(self) -> str:
        """SVG attribute fill used for the full-map background rect.

        Honors `map.background` when set; otherwise falls through to the
        subclass default. Registers any referenced texture pattern.
        """
        return self._resolve_bg(self.dmap.map.background) or self._bg_default()

    def _extra_defs_block(self) -> str:
        """Optional `<defs>...</defs>` injected before the stylesheet.

        Subclasses can override to register `<pattern>` etc.
        """
        return ""

    def _pre_rooms_layer(self) -> str:
        """Optional SVG fragment drawn between the background rect and the
        rooms group. Subclasses use this to lay down content that should
        sit *under* the floor fills (e.g. the hatched halo).
        """
        return ""

    # --- rooms ---

    def _room_floor(self, r: Room) -> str:
        d = self._room_path(r)
        number = self.room_numbers.get(r.name)
        attrs = f'class="floor" data-room="{escape(r.name)}"'
        if number is not None:
            attrs += f' data-number="{number}"'
        if r.label is not None and r.label.text:
            attrs += f' data-label="{escape(r.label.text)}"'
        if r.description:
            attrs += f' data-description="{escape(r.description)}"'
        if r.dm_notes:
            attrs += f' data-dm-notes="{escape(r.dm_notes)}"'
        # Per-room background override (color or named texture). Must be
        # emitted as an inline `style` (not a `fill="..."` presentation
        # attribute) because the `.floor` class in the stylesheet declares
        # `fill:#fafafa`, and SVG/CSS specificity makes class rules win
        # over presentation attributes. Inline style beats both.
        bg = self._resolve_bg(r.background)
        if bg is not None:
            attrs += f' style="fill:{bg}"'
        attrs += self._organic_filter_attr(r.line_style, r.line_style_amount)
        return f"<path {attrs} d=\"{d}\"/>"

    def _area(self, a: Area) -> str:
        """Render a decorative terrain area as a filled shape.

        Reuses the room path builder (the shape grammar is shared), fills with
        the kind palette (or an explicit `background`), strokes a subtle
        outline, and applies the organic edge filter when requested."""
        d = self._room_path(Room(name=a.name, shape=a.shape))
        if not d:
            return ""
        kind_fill, kind_stroke = AREA_KINDS.get(a.kind, AREA_KINDS["_default"])
        fill = self._resolve_bg(a.background) or self._resolve_bg(kind_fill) or "#9fb0bd"
        attrs = (
            f'class="area" data-area="{escape(a.name)}" '
            f'data-kind="{escape(a.kind)}"'
        )
        if a.label is not None and a.label.text:
            attrs += f' data-label="{escape(a.label.text)}"'
        if a.description:
            attrs += f' data-description="{escape(a.description)}"'
        if a.dm_notes:
            attrs += f' data-dm-notes="{escape(a.dm_notes)}"'
        attrs += self._organic_filter_attr(a.line_style, a.line_style_amount)
        style = (
            f"fill:{fill};stroke:{kind_stroke};"
            f"stroke-width:{_n(AREA_OUTLINE_STROKE)};stroke-linejoin:round"
        )
        label = self._room_label_for_area(a)
        return f'<path {attrs} style="{style}" d="{d}"/>' + label

    def _room_label_for_area(self, a: Area) -> str:
        """Draw an area's label, if any, reusing room-label placement."""
        if a.label is None:
            return ""
        return self._room_label(Room(name=a.name, shape=a.shape, label=a.label))

    def _room_bbox(self, r: Room) -> tuple[float, float, float, float]:
        walls = room_walls(r)
        xs: list[float] = []
        ys: list[float] = []
        for w in walls:
            xs.extend([w.a[0], w.b[0]])
            ys.extend([w.a[1], w.b[1]])
            if isinstance(w, ArcWall):
                xs.append(w.via[0])
                ys.append(w.via[1])
        return min(xs), min(ys), max(xs), max(ys)

    def _map_grid_overlay(
        self, spacing: float, color: str | None
    ) -> str:
        """Faint graph-paper grid covering the full canvas. Used when the
        map config has `grid_overlay <spacing>` set."""
        lines: list[str] = []
        # Vertical lines from x = spacing to x = W (skip the 0 and W edges —
        # those would sit on the canvas border and double the outline).
        x = spacing
        while x < self.W - 1e-9:
            lines.append(
                f'<line x1="{_n(x)}" y1="0" '
                f'x2="{_n(x)}" y2="{_n(self.H)}"/>'
            )
            x += spacing
        # Horizontal lines.
        y = spacing
        while y < self.H - 1e-9:
            lines.append(
                f'<line x1="0" y1="{_n(y)}" '
                f'x2="{_n(self.W)}" y2="{_n(y)}"/>'
            )
            y += spacing
        if not lines:
            return ""
        stroke_attr = f' stroke="{escape(color)}"' if color else ""
        return (
            f'<g class="map-grid"{stroke_attr}>{"".join(lines)}</g>'
        )

    def _cell_grid_lines(self, clip: list[str], clip_id: str) -> str:
        """Grid lines across the canvas, clipped to `clip` shapes. Shared by
        the room pass (drawn under walls) and the corridor pass."""
        spacing = self.dmap.map.cell_grid
        if not spacing or spacing <= 0 or not clip:
            return ""
        lines: list[str] = []
        n = 1
        while n * spacing < self.W:
            x = n * spacing
            lines.append(f'<line x1="{_n(x)}" y1="0" x2="{_n(x)}" y2="{_n(self.H)}"/>')
            n += 1
        n = 1
        while n * spacing < self.H:
            y = n * spacing
            lines.append(f'<line x1="0" y1="{_n(y)}" x2="{_n(self.W)}" y2="{_n(y)}"/>')
            n += 1
        if not lines:
            return ""
        color = self.dmap.map.cell_grid_color
        # Inline `style` so it beats the `.room-grid` CSS; lines inherit it.
        stroke_attr = f' style="stroke:{escape(color)}"' if color else ""
        return (
            f'<defs><clipPath id="{clip_id}">{"".join(clip)}</clipPath></defs>'
            f'<g class="room-grid" clip-path="url(#{clip_id})"'
            f'{stroke_attr}>{"".join(lines)}</g>'
        )

    def _cell_grid_rooms(self) -> str:
        """Cell grid clipped to room areas (rooms with their own `grid` win)."""
        clip = [
            f'<path d="{self._room_path(r)}"/>'
            for r in self.all_rooms.values()
            if r.grid is None
        ]
        return self._cell_grid_lines(clip, "dungml-cell-grid-rooms")

    def _cell_grid_corridors(self, all_corridors: list[Corridor]) -> str:
        """Cell grid clipped to corridor areas."""
        clip: list[str] = []
        for c in all_corridors:
            for poly in corridor_polygons(c):
                pts = " ".join(f"{_n(p[0])},{_n(self.y(p[1]))}" for p in poly)
                clip.append(f'<polygon points="{pts}"/>')
        return self._cell_grid_lines(clip, "dungml-cell-grid-corr")

    def _room_grid_overlay(self, r: Room) -> str:
        if r.grid is None or r.grid <= 0:
            return ""
        spacing = r.grid
        minx, miny, maxx, maxy = self._room_bbox(r)
        clip_id = f"gridclip-{_slug(r.name)}"
        clip_path = self._room_path(r)
        lines: list[str] = []
        # Vertical lines: aligned to integer multiples of `spacing`.
        n = math.ceil(minx / spacing)
        while True:
            x = n * spacing
            if x > maxx + 1e-9:
                break
            if x >= minx - 1e-9:
                lines.append(
                    f'<line x1="{_n(x)}" y1="{_n(self.y(miny))}" '
                    f'x2="{_n(x)}" y2="{_n(self.y(maxy))}"/>'
                )
            n += 1
        # Horizontal lines.
        n = math.ceil(miny / spacing)
        while True:
            y = n * spacing
            if y > maxy + 1e-9:
                break
            if y >= miny - 1e-9:
                lines.append(
                    f'<line x1="{_n(minx)}" y1="{_n(self.y(y))}" '
                    f'x2="{_n(maxx)}" y2="{_n(self.y(y))}"/>'
                )
            n += 1
        if not lines:
            return ""
        # Inline `style` (not a presentation attr) so it beats the `.room-grid`
        # CSS; lines inherit the stroke.
        stroke_attr = (
            f' style="stroke:{escape(r.grid_color)}"' if r.grid_color else ""
        )
        return (
            f'<defs><clipPath id="{clip_id}">'
            f'<path d="{clip_path}"/></clipPath></defs>'
            f'<g class="room-grid" data-room="{escape(r.name)}" '
            f'clip-path="url(#{clip_id})"{stroke_attr}>{"".join(lines)}</g>'
        )

    def _room_walls(
        self,
        r: Room,
        doors: list[Door],
        windows: list[Window],
    ) -> str:
        walls = room_walls(r)
        line_walls: list[LineWall] = []
        arc_walls: list[ArcWall] = []
        for w in walls:
            if isinstance(w, LineWall):
                line_walls.append(w)
            else:
                arc_walls.append(w)

        # Build per-wall cut intervals from doors and windows.
        cuts: list[list[tuple[float, float]]] = [[] for _ in line_walls]
        for d in doors:
            if not _door_touches_room(d, r):
                continue
            if d.type == "secret":
                # Secret doors don't open the wall — they sit ON the wall
                # as a small "S" marker. Skip the cut.
                continue
            self._record_cut(d.position, d.width or DOOR_WIDTH_DEFAULT,
                             line_walls, cuts)
        for win in windows:
            if _strip_kind(win.in_ref) != r.name:
                continue
            self._record_cut(win.position, win.width, line_walls, cuts)

        trail = r.line_style == "trail"
        pieces: list[str] = []
        for idx, w in enumerate(line_walls):
            for piece in _apply_cuts(w, cuts[idx]):
                pieces.append(
                    self._trail_marks(piece) if trail
                    else self._line_to_svg(piece)
                )
        for aw in arc_walls:
            # Trail x-marks along a curve aren't supported; arcs stay solid.
            pieces.append(self._arc_wall_to_svg(aw))

        filter_attr = self._organic_filter_attr(r.line_style, r.line_style_amount)
        # Dash-pattern styles tag the group so a `.<style> .wall` rule applies
        # (see the stylesheet). `trail` draws its own marks, no group class.
        cls = (
            r.line_style
            if r.line_style in ("ruined", "dotted", "dashed")
            else None
        )
        cls_attr = f' class="{cls}"' if cls else ""
        return (
            f'<g data-room="{escape(r.name)}"{cls_attr}{filter_attr}>'
            + "".join(pieces)
            + "</g>"
        )

    def _record_cut(
        self,
        position: Vec2,
        width: float,
        line_walls: list[LineWall],
        cuts: list[list[tuple[float, float]]],
    ) -> None:
        best_idx: int | None = None
        best_dist = float("inf")
        best_t = 0.0
        for i, w in enumerate(line_walls):
            _, t, dist = project_onto_wall(position, w)
            if dist < best_dist:
                best_dist = dist
                best_idx = i
                best_t = t
        if best_idx is None:
            return
        # Tolerance: must be on (or near) the wall. Generous enough that
        # a door authored at an integer coord still snaps onto a diagonal
        # wall passing close to it (perpendicular distance to a 5-unit
        # diagonal off an integer grid can exceed 0.5 by a hair).
        if best_dist > 1.0:
            return
        L = wall_length(line_walls[best_idx]) or 1.0
        half_t = (width / 2.0) / L
        cuts[best_idx].append((best_t - half_t, best_t + half_t))

    def _room_path(self, r: Room) -> str:
        """SVG path data covering the room's floor area."""
        walls = room_walls(r)
        if not walls:
            return ""
        first = walls[0]
        start = first.a
        parts = [f"M {_n(start[0])},{_n(self.y(start[1]))}"]
        for w in walls:
            if isinstance(w, LineWall):
                parts.append(f"L {_n(w.b[0])},{_n(self.y(w.b[1]))}")
            else:
                parts.append(self._arc_path_segment(w))
        parts.append("Z")
        return " ".join(parts)

    # --- corridors ---

    def _corridor(self, c: Corridor) -> str:
        """Render a corridor as two stacked strokes of the centerline.

        Outer stroke (wide, dark) draws the walls; inner stroke (slightly
        narrower, floor-coloured) carves the corridor band on top. L-junctions
        and arc transitions sort themselves out naturally because both strokes
        follow the same path — no parallel-wall stitching needed.
        """
        floor_d = self._corridor_path(c)
        if not floor_d:
            return ""
        display = c.display_name or c.name
        attrs = f'data-corridor="{escape(c.name)}" data-label="{escape(display)}"'
        if c.description:
            attrs += f' data-description="{escape(c.description)}"'
        if c.dm_notes:
            attrs += f' data-dm-notes="{escape(c.dm_notes)}"'
        filter_attr = self._organic_filter_attr(c.line_style, c.line_style_amount)
        # Corner style at bends/junctions: round (default) or straight (sharp).
        join = "miter" if c.corners == "straight" else "round"
        label_layer = self._corridor_label(c) if c.label is not None else ""

        # Zero-width corridor: draw the centerline as a single line (a route
        # or passage marker) — no parallel walls, no floor band. `line_style`
        # styles the line: trail draws x-marks along it; dotted/dashed/ruined
        # apply the matching dash pattern.
        if c.width <= 0:
            if c.line_style == "trail":
                marks = []
                for seg in c.segments:
                    if isinstance(seg, LineSegment):
                        marks.append(
                            self._trail_marks_between(seg.start, seg.end)
                        )
                    else:
                        # arc segment: x-marks along a curve aren't supported,
                        # fall back to a thin solid stroke of just this arc.
                        d = (
                            f"M {_n(_arc_endpoint(seg, seg.from_angle)[0])},"
                            f"{_n(self.y(_arc_endpoint(seg, seg.from_angle)[1]))} "
                            + self._arc_segment_path(seg)
                        )
                        marks.append(
                            f'<path class="corridor-wall" d="{d}" '
                            f'stroke-width="{_n(WALL_STROKE)}" stroke="#111" '
                            f'stroke-linejoin="{join}" fill="none"/>'
                        )
                return (
                    f'<g {attrs}>{"".join(marks)}</g>{label_layer}'
                )
            dash, cap = self._centerline_dash(c.line_style)
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
            line_layer = (
                f'<path class="corridor-wall" {attrs} d="{floor_d}" '
                f'stroke-width="{_n(WALL_STROKE)}" stroke="#111" '
                f'stroke-linejoin="{join}" stroke-linecap="{cap}"{dash_attr} '
                f'fill="none"{filter_attr}/>'
            )
            return line_layer + label_layer

        outline_w = c.width + 2 * WALL_STROKE
        # Wall outline (drawn first, wider, dark).
        wall_layer = (
            f'<path class="corridor-wall" {attrs} d="{floor_d}" '
            f'stroke-width="{_n(outline_w)}" stroke="#111" '
            f'stroke-linejoin="{join}" stroke-linecap="butt" fill="none"'
            f"{filter_attr}/>"
        )
        # Floor layer (drawn second, narrower, floor colour or override).
        floor_stroke = self._resolve_bg(c.background) or self._corridor_floor_fill()
        floor_layer = (
            f'<path class="corridor-floor" {attrs} d="{floor_d}" '
            f'stroke-width="{_n(c.width)}" stroke="{floor_stroke}" '
            f'stroke-linejoin="{join}" stroke-linecap="butt" fill="none"'
            f"{filter_attr}/>"
        )
        # On-map label only when the corridor declares an explicit `label`
        # block. The display_name (second STRING after the slug) is for
        # tooltips and the print legend only — it never renders on the map.
        label_layer = self._corridor_label(c) if c.label is not None else ""
        return wall_layer + floor_layer + label_layer

    def _corridor_label(self, c: Corridor) -> str:
        """Draw an explicit corridor label.

        Position priority mirrors room labels:
          1. `at X,Y` → absolute world coords
          2. `align V H` → anchored inside the corridor's centerline bbox
          3. neither → centered along the longest line segment, rotated to
             read along the corridor's direction (the "natural" placement)

        `rotate N` is honored in all three cases; in mode 3 it stacks on
        top of the auto-derived along-segment angle.
        """
        lbl = c.label
        if lbl is None:
            return ""
        auto_angle = 0.0
        anchor_h = "middle"
        baseline = "central"
        if lbl.position is not None:
            mx, my = lbl.position
        elif lbl.align_v is not None or lbl.align_h is not None:
            mx, my, anchor_h, baseline = self._label_anchor_from_align(
                self._corridor_bbox(c), lbl.align_v, lbl.align_h
            )
        else:
            mx, my, auto_angle = self._corridor_auto_anchor(c)
            if mx is None:
                return ""
            # Flip text that would read upside-down along the segment.
            if auto_angle > 90 or auto_angle < -90:
                auto_angle += 180
        angle = auto_angle + lbl.rotate
        size = LABEL_BASE_SIZE * lbl.size
        text = escape(lbl.text)
        if self.flip_y:
            transform = (
                f"translate({_n(mx)},{_n(self.y(my))}) "
                f"rotate({_n(-angle)}) scale(1,-1)"
            )
        else:
            transform = (
                f"translate({_n(mx)},{_n(my)}) rotate({_n(angle)})"
            )
        return (
            f'<text class="label corridor-label" transform="{transform}" '
            f'text-anchor="{anchor_h}" dominant-baseline="{baseline}" '
            f'font-size="{_n(size)}">{text}</text>'
        )

    def _slice_label(self, s: "Slice") -> str:
        """Same priority rules as `_corridor_label` — explicit `label "..."`
        block, position-or-align-or-auto-along-segment. Reuses the corridor
        anchor helpers since slices share the line/arc segments shape.
        """
        lbl = s.label
        if lbl is None:
            return ""
        auto_angle = 0.0
        anchor_h = "middle"
        baseline = "central"
        if lbl.position is not None:
            mx, my = lbl.position
        elif lbl.align_v is not None or lbl.align_h is not None:
            mx, my, anchor_h, baseline = self._label_anchor_from_align(
                self._corridor_bbox(s),  # works on anything with .segments
                lbl.align_v,
                lbl.align_h,
            )
        else:
            mx, my, auto_angle = self._corridor_auto_anchor(s)
            if mx is None:
                return ""
            if auto_angle > 90 or auto_angle < -90:
                auto_angle += 180
        angle = auto_angle + lbl.rotate
        size = LABEL_BASE_SIZE * lbl.size
        text = escape(lbl.text)
        if self.flip_y:
            transform = (
                f"translate({_n(mx)},{_n(self.y(my))}) "
                f"rotate({_n(-angle)}) scale(1,-1)"
            )
        else:
            transform = (
                f"translate({_n(mx)},{_n(my)}) rotate({_n(angle)})"
            )
        return (
            f'<text class="label slice-label" transform="{transform}" '
            f'text-anchor="{anchor_h}" dominant-baseline="{baseline}" '
            f'font-size="{_n(size)}">{text}</text>'
        )

    def _corridor_auto_anchor(
        self, c: Corridor
    ) -> tuple[float | None, float | None, float]:
        """Pick a label anchor along the corridor's longest line segment,
        or fall back to the midpoint of an arc segment. Returns
        (x, y, angle_deg). x is None if the corridor has no segments.
        """
        best_line: LineSegment | None = None
        best_len = 0.0
        for s in c.segments:
            if isinstance(s, LineSegment):
                dx = s.end[0] - s.start[0]
                dy = s.end[1] - s.start[1]
                L = (dx * dx + dy * dy) ** 0.5
                if L > best_len:
                    best_len = L
                    best_line = s
        if best_line is not None:
            mx = (best_line.start[0] + best_line.end[0]) / 2.0
            my = (best_line.start[1] + best_line.end[1]) / 2.0
            dx = best_line.end[0] - best_line.start[0]
            dy = best_line.end[1] - best_line.start[1]
            return mx, my, math.degrees(math.atan2(dy, dx))
        arc = next((s for s in c.segments if isinstance(s, ArcSegment)), None)
        if arc is None:
            return None, None, 0.0
        mid_angle = (arc.from_angle + arc.to_angle) / 2.0
        mx, my = _arc_endpoint(arc, mid_angle)
        return mx, my, 0.0

    def _corridor_bbox(
        self, c: Corridor
    ) -> tuple[float, float, float, float]:
        """Bounding box of the corridor's centerline. Arcs sampled at ~5°."""
        xs: list[float] = []
        ys: list[float] = []
        for s in c.segments:
            if isinstance(s, LineSegment):
                xs.extend([s.start[0], s.end[0]])
                ys.extend([s.start[1], s.end[1]])
            else:
                # Sample arc into a polyline for the bbox.
                lo, hi = sorted((s.from_angle, s.to_angle))
                step = 5.0
                ang = lo
                while ang <= hi:
                    px, py = _arc_endpoint(s, ang)
                    xs.append(px)
                    ys.append(py)
                    ang += step
                # Include exact endpoints.
                for a in (s.from_angle, s.to_angle):
                    px, py = _arc_endpoint(s, a)
                    xs.append(px)
                    ys.append(py)
        if not xs:
            return 0.0, 0.0, 0.0, 0.0
        return min(xs), min(ys), max(xs), max(ys)

    def _party_start(self, pos: Vec2) -> str:
        """A start marker (filled disc + 'S') at the party's starting cell."""
        x, y = pos
        cy = self.y(y)
        return (
            f'<g class="party-start" data-label="Party start" '
            f'data-description="Starting position">'
            f'<circle cx="{_n(x)}" cy="{_n(cy)}" r="0.42" '
            f'fill="#2aa05a" stroke="#0f3d22" stroke-width="0.1"/>'
            f'<text x="{_n(x)}" y="{_n(cy)}" font-family="Georgia,serif" '
            f'font-size="0.6" fill="#fff" text-anchor="middle" '
            f'dominant-baseline="central">S</text>'
            f"</g>"
        )

    def _corridor_path(self, c: Corridor) -> str:
        """Build the centerline path, starting a fresh sub-path whenever a
        segment does not continue from where the previous one ended.

        Contiguous chains (a straight run, an L-bend, an arc transition) stay
        one sub-path so wall joins round cleanly — output is identical to the
        old single-polyline form. Branches and crossings (segments that fan
        out from a shared point) become separate sub-paths that meet at the
        junction, which the two-stroke wall/floor draw resolves automatically.

        A segment that doubles back ~180° over the previous one also starts a
        fresh sub-path: a round line-join on a U-turn would otherwise bulge out
        as a semicircle (e.g. a spur that retraces part of a run).
        """
        if not c.segments:
            return ""
        parts: list[str] = []
        pen: Vec2 | None = None
        prev_dir: Vec2 | None = None
        for s in c.segments:
            if isinstance(s, LineSegment):
                start, end = s.start, s.end
            else:
                start = _arc_endpoint(s, s.from_angle)
                end = _arc_endpoint(s, s.to_angle)
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dx, dy) or 1.0
            cur_dir = (dx / length, dy / length)
            contiguous = (
                pen is not None
                and abs(start[0] - pen[0]) <= 1e-6
                and abs(start[1] - pen[1]) <= 1e-6
            )
            u_turn = (
                contiguous
                and prev_dir is not None
                and cur_dir[0] * prev_dir[0] + cur_dir[1] * prev_dir[1] < -0.999
            )
            if not contiguous or u_turn:
                parts.append(f"M {_n(start[0])},{_n(self.y(start[1]))}")
            if isinstance(s, LineSegment):
                parts.append(f"L {_n(end[0])},{_n(self.y(end[1]))}")
            else:
                parts.append(self._arc_segment_path(s))
            pen = end
            prev_dir = cur_dir
        return " ".join(parts)

    def _corridor_walls(self, c: Corridor) -> list[LineWall]:
        """Two parallel line walls bracketing each corridor segment."""
        out: list[LineWall] = []
        half = c.width / 2.0
        for s in c.segments:
            if isinstance(s, LineSegment):
                ax, ay = s.start
                bx, by = s.end
                dx, dy = bx - ax, by - ay
                L = (dx * dx + dy * dy) ** 0.5 or 1.0
                nx, ny = -dy / L, dx / L
                out.append(
                    LineWall(
                        (ax + nx * half, ay + ny * half),
                        (bx + nx * half, by + ny * half),
                    )
                )
                out.append(
                    LineWall(
                        (ax - nx * half, ay - ny * half),
                        (bx - nx * half, by - ny * half),
                    )
                )
            # Arc-segment walls left as a future enhancement; the
            # corridor floor still renders along the centerline.
        return out

    # --- slices (cross-slice terrain) ---

    # Per-kind palette: (bank_color, fill_color, accent_color).
    # bank is the outer outline, fill is the wide stroke, accent is the
    # subtle centerline detail layered on top (flow lines, shadow, crack).
    _SLICE_PALETTE = {
        "river":  ("#3f5d6c", "#a8c5d8", "#7aa0b6"),
        "ravine": ("#1f140a", "#5a4630", "#1a1208"),
        "split":  ("#0e0e0e", "#1c1c1c", "#000000"),
    }

    def _slice(self, s: "Slice") -> str:
        """Render a cross-slice (river / ravine / split) as a stroked
        band along its centerline. Three SVG paths stacked:

          1. outer bank stroke (slightly wider, darker bank color),
          2. inner band stroke (the slice width, kind-specific fill),
          3. centerline accent (thin dashed/dotted detail).

        The split kind is treated specially — it ignores the configured
        width and renders as a thin dark crack (with a faint shadow
        underneath), since splits are visually narrow by nature.
        """
        path_d = self._corridor_path(s)  # reuses corridor's line/arc path
        if not path_d:
            return ""
        bank, fill, accent = self._SLICE_PALETTE.get(
            s.kind, self._SLICE_PALETTE["river"]
        )
        attrs = (
            f'data-slice="{escape(s.name)}" '
            f'data-kind="{escape(s.kind)}" '
            f'data-label="{escape(s.label.text if s.label else s.name)}"'
        )
        if s.description:
            attrs += f' data-description="{escape(s.description)}"'
        if s.dm_notes:
            attrs += f' data-dm-notes="{escape(s.dm_notes)}"'

        if s.kind == "split":
            # A narrow crack. Shadow + crack-line; the configured width
            # acts as a soft shadow width.
            shadow_w = max(s.width * 0.4, 0.25)
            crack_w = 0.10
            return (
                f'<path class="slice slice-split-shadow" {attrs} d="{path_d}" '
                f'stroke="{accent}" stroke-width="{_n(shadow_w)}" '
                f'fill="none" stroke-linejoin="round" stroke-linecap="round" '
                f'opacity="0.35"/>'
                f'<path class="slice slice-split" {attrs} d="{path_d}" '
                f'stroke="{bank}" stroke-width="{_n(crack_w)}" '
                f'fill="none" stroke-linejoin="round" stroke-linecap="round"/>'
            )

        bank_w = s.width + 2 * 0.16
        # bank
        out = (
            f'<path class="slice slice-bank" {attrs} d="{path_d}" '
            f'stroke="{bank}" stroke-width="{_n(bank_w)}" '
            f'fill="none" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        # filled band (water / dirt)
        out += (
            f'<path class="slice slice-fill" {attrs} d="{path_d}" '
            f'stroke="{fill}" stroke-width="{_n(s.width)}" '
            f'fill="none" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        # accent (flow lines for river, deep shadow for ravine)
        if s.kind == "river":
            accent_w = max(0.04, s.width * 0.06)
            dash = f"{_n(s.width * 0.35)},{_n(s.width * 0.5)}"
            out += (
                f'<path class="slice slice-flow" {attrs} d="{path_d}" '
                f'stroke="{accent}" stroke-width="{_n(accent_w)}" '
                f'fill="none" stroke-linejoin="round" stroke-linecap="round" '
                f'stroke-dasharray="{dash}" opacity="0.7"/>'
            )
        elif s.kind == "ravine":
            shadow_w = s.width * 0.4
            out += (
                f'<path class="slice slice-depth" {attrs} d="{path_d}" '
                f'stroke="{accent}" stroke-width="{_n(shadow_w)}" '
                f'fill="none" stroke-linejoin="round" stroke-linecap="round" '
                f'opacity="0.55"/>'
            )
        return out

    # --- doors / windows ---

    def _door(self, d: Door) -> str:
        wall_info = self._find_door_wall(d)
        # A door on a corridor's *side* wall needs the corridor's stroked wall
        # opened too (rooms auto-cut, corridors don't) — paint a floor patch.
        marker = d.type in ("secret", "concealed")
        patch = ""
        if not marker:
            patch = self._corridor_opening_patch(d) + self._corridor_end_mouth(d)
        if marker:
            letter = "S" if d.type == "secret" else "C"
            body = self._marker_door_symbol(d, wall_info, letter, d.type)
        elif wall_info is None:
            cx, cy = d.position
            body = (
                f'<circle class="door" cx="{_n(cx)}" cy="{_n(self.y(cy))}" '
                f'r="{_n((d.width or DOOR_WIDTH_DEFAULT) / 4)}"/>'
            )
        else:
            body = self._door_leaf(d, wall_info)
        return self._wrap_door(d, patch + body)

    def _corridor_opening_patch(self, d: Door) -> str:
        """Erase the corridor wall stroke at a door that sits on a corridor's
        side edge, so the opening reads as a gap. Safe because both sides of
        that edge are floor; returns "" for doors not on a corridor side."""
        edge = self._door_corridor_edge(d)
        if edge is None:
            return ""
        (ax, ay), (bx, by) = edge
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1.0
        ux, uy = dx / L, dy / L
        nx, ny = -uy, ux
        cx, cy = d.position
        half = (d.width or DOOR_WIDTH_DEFAULT) / 2.0
        perp = WALL_STROKE + 0.06
        corners = [
            (cx - half * ux - perp * nx, cy - half * uy - perp * ny),
            (cx + half * ux - perp * nx, cy + half * uy - perp * ny),
            (cx + half * ux + perp * nx, cy + half * uy + perp * ny),
            (cx - half * ux + perp * nx, cy - half * uy + perp * ny),
        ]
        pts = " ".join(f"{_n(x)},{_n(self.y(y))}" for x, y in corners)
        return (
            f'<polygon class="door-opening" points="{pts}" '
            f'fill="{self._corridor_floor_fill()}" stroke="none"/>'
        )

    def _door_corridor_edge(self, d: Door) -> tuple[Vec2, Vec2] | None:
        """If `d` sits on a connected corridor's side edge, return that
        corridor segment's endpoints (to orient the opening patch)."""
        corrs = dict(self.dmap.corridors)
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            for c in layer.corridors:
                corrs.setdefault(c.name, c)
        for ref in d.connects:
            if not ref.startswith("corridor."):
                continue
            c = corrs.get(ref.split(".", 1)[1])
            if c is None:
                continue
            half = c.width / 2.0
            for s in c.segments:
                if not isinstance(s, LineSegment):
                    continue
                dist = _point_segment_dist(d.position, s.start, s.end)
                # Near the long edge (≈ half-width away), not the centreline
                # (an end-door) or far away.
                if half - 0.3 <= dist <= half + WALL_STROKE + 0.15:
                    return s.start, s.end
        return None

    def _corridor_end_at(
        self, d: Door
    ) -> tuple[Corridor, Vec2, Vec2, float, float] | None:
        """If a corridor connected to `d` *terminates* near the door, return
        (corridor, end_point, outward_unit_dir, half_width, terminal_seg_len).

        Only degree-1 endpoints (true corridor ends, not bends or junctions)
        qualify; a door on a corridor's side or partway along it is handled by
        `_corridor_opening_patch`, not here."""
        corrs = dict(self.dmap.corridors)
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            for c in layer.corridors:
                corrs.setdefault(c.name, c)
        cx, cy = d.position
        best: tuple[float, Corridor, Vec2, Vec2, float] | None = None
        for ref in d.connects:
            if not ref.startswith("corridor."):
                continue
            c = corrs.get(ref.split(".", 1)[1])
            if c is None:
                continue
            half = c.width / 2.0
            # (endpoint, other end) for every line-segment end.
            ends: list[tuple[Vec2, Vec2]] = []
            for s in c.segments:
                if isinstance(s, LineSegment):
                    ends.append((s.start, s.end))
                    ends.append((s.end, s.start))
            tol = max(half, 0.5) + 0.25
            for pt, other in ends:
                degree = sum(
                    1
                    for q, _ in ends
                    if abs(q[0] - pt[0]) <= 1e-6 and abs(q[1] - pt[1]) <= 1e-6
                )
                if degree != 1:
                    continue  # bend or junction, not a free end
                dist = math.hypot(pt[0] - cx, pt[1] - cy)
                if dist > tol:
                    continue
                dx, dy = pt[0] - other[0], pt[1] - other[1]
                L = math.hypot(dx, dy) or 1.0
                if best is None or dist < best[0]:
                    best = (dist, c, pt, (dx / L, dy / L), half, L)
        if best is None:
            return None
        _, c, pt, u, half, seg_len = best
        return c, pt, u, half, seg_len

    def _corridor_end_mouth(self, d: Door) -> str:
        """Square a corridor's end to the wall it opens into.

        A corridor is stroked along its centerline with a butt cap, so its
        end is cut perpendicular to the corridor's *own* direction. Where a
        (typically diagonal) corridor meets a wall at an oblique angle, that
        cap diverges from the wall — leaving a skewed gap and a misangled dark
        cap. This paints a floor quad that bridges the wall: squared to the
        wall angle, pulled back into the corridor to cover the butt cap, and
        pushed just past the wall to bury the door gap's jamb caps and meet
        the room floor — so the join reads as one continuous opening.

        Suppressed (returns "") when the corridor already ends on the wall
        perpendicularly (the gap is zero-length), so axis-aligned maps render
        unchanged."""
        end = self._corridor_end_at(d)
        if end is None:
            return ""
        c, (ex, ey), (ux, uy), half, seg_len = end
        wall_info = self._find_door_wall(d)
        if wall_info is None:
            return ""
        wall, _t = wall_info
        nx, ny = -uy, ux
        pL = (ex + nx * half, ey + ny * half)
        pR = (ex - nx * half, ey - ny * half)
        iL = _line_intersect(pL, (ux, uy), wall.a, wall.b)
        iR = _line_intersect(pR, (ux, uy), wall.a, wall.b)
        if iL is None or iR is None:
            return ""
        extL = math.hypot(iL[0] - pL[0], iL[1] - pL[1])
        extR = math.hypot(iR[0] - pR[0], iR[1] - pR[1])
        # Skip a degenerate mouth: a corridor already ending on the wall
        # perpendicularly needs no patch (and clutters output for every
        # axis-aligned end door otherwise).
        if extL < 1e-6 and extR < 1e-6:
            return ""
        # Guard against a mismatched wall pulling the mouth far across the map.
        max_ext = c.width * 2.0 + 1.0
        if extL > max_ext or extR > max_ext:
            return ""
        # Bridge the wall so the join reads clean. `u` points out of the
        # corridor and through the wall into the connected room, so:
        #   - pull the near edge back into the corridor (-u) to overlap the
        #     floor stroke's butt cap (else a hairline seam shows), and
        #   - push the far edge just past the wall (+u) — far enough to bury
        #     the wall's jamb caps (the dark nubs) and overlap the room floor,
        #     but not so far it pokes a floor-coloured wedge deep into an
        #     organic-filtered cave that renders darker than the corridor.
        # The patch draws in the doors group, on top of walls and corridors.
        back = min(WALL_STROKE, seg_len * 0.4)
        fwd = WALL_STROKE
        bL = (pL[0] - ux * back, pL[1] - uy * back)
        bR = (pR[0] - ux * back, pR[1] - uy * back)
        fL = (iL[0] + ux * fwd, iL[1] + uy * fwd)
        fR = (iR[0] + ux * fwd, iR[1] + uy * fwd)
        corners = [bL, fL, fR, bR]
        pts = " ".join(f"{_n(x)},{_n(self.y(y))}" for x, y in corners)
        fill = self._resolve_bg(c.background) or self._corridor_floor_fill()
        return (
            f'<polygon class="corridor-mouth" data-corridor="{escape(c.name)}" '
            f'points="{pts}" fill="{fill}" stroke="none"/>'
        )

    def _door_leaf(self, d: Door, wall_info: tuple[LineWall, float]) -> str:
        """Draw a door glyph in the gap cut from the wall.

        Glyph repertoire (matches a standard dungeon-map legend):

        - `open` / `opening` / `gap`: nothing drawn — just the gap cut from
          the wall (still a real connector in the graph)
        - `arch` / `archway`: two perpendicular jamb ticks, no leaf
        - `portcullis`: two rails along the wall with vertical bars between
        - everything else (`wooden`, `iron`, `stone`, …): jamb ticks plus a
          solid leaf parallel to the wall

        Door `state` adds a sub-glyph on top of the leaf:
        - `open`: leaf is suppressed, an arc and a swing-line replace it
        - `locked`: small filled dot at the leaf centre (keyhole)
        - `trapped`: small X mark on the leaf
        """
        wall, t = wall_info
        ax, ay = wall.a
        bx, by = wall.b
        dx, dy = bx - ax, by - ay
        L = (dx * dx + dy * dy) ** 0.5 or 1.0
        ux, uy = dx / L, dy / L
        nx, ny = -uy, ux
        cx = ax + t * dx
        cy = ay + t * dy
        half = (d.width or DOOR_WIDTH_DEFAULT) / 2.0
        dtype = (d.type or "wooden").lower()
        state = (d.state or "closed").lower()

        if dtype in ("open", "opening", "gap"):
            return ""  # bare opening: gap is already cut from the wall
        if dtype in ("arch", "archway"):
            return self._jamb_ticks(cx, cy, ux, uy, nx, ny, half, 0.22)
        if dtype in ("smashed", "broken"):
            # Broken-down door: an arch (no leaf) littered with debris.
            return (
                self._jamb_ticks(cx, cy, ux, uy, nx, ny, half, 0.22)
                + self._debris_marks(cx, cy, ux, uy, nx, ny, half)
            )
        if dtype == "portcullis":
            return self._portcullis_symbol(cx, cy, ux, uy, nx, ny, half)
        if dtype in ("gate", "gates"):
            return self._gates_symbol(cx, cy, ux, uy, nx, ny, half)

        # Trap glyph: shown for the legacy `state trapped` OR the orthogonal
        # `trapped` flag (so e.g. a locked door can also read as trapped).
        # GM information — fog-of-war strips the flag from the players' view.
        trap = (
            self._trap_mark(cx, cy, ux, uy, nx, ny)
            if (d.trapped or state == "trapped")
            else ""
        )
        parts = [self._jamb_ticks(cx, cy, ux, uy, nx, ny, half, 0.18)]
        if state == "open":
            parts.append(self._open_swing(cx, cy, ux, uy, nx, ny, half))
            parts.append(trap)
            return "".join(parts)
        if dtype in ("double", "double-door", "double_door"):
            # Two leaves meeting at the centre of the opening.
            h = half / 2.0
            parts.append(self._closed_leaf(cx - h * ux, cy - h * uy, ux, uy, nx, ny, h))
            parts.append(self._closed_leaf(cx + h * ux, cy + h * uy, ux, uy, nx, ny, h))
        else:
            parts.append(self._closed_leaf(cx, cy, ux, uy, nx, ny, half))
        if dtype in ("one-way", "oneway", "one_way"):
            parts.append(
                self._oneway_arrow(cx, cy, ux, uy, nx, ny, self._oneway_sign(d, nx, ny))
            )
        if state == "locked":
            parts.append(self._lock_dot(cx, cy))
        parts.append(trap)
        return "".join(parts)

    def _oneway_sign(self, d: Door, nx: float, ny: float) -> float:
        """Which way along the wall normal the one-way arrow points, from the
        door's `facing` (defaults to the +normal side)."""
        vec = {
            "north": (0.0, -1.0), "south": (0.0, 1.0),
            "east": (1.0, 0.0), "west": (-1.0, 0.0),
        }.get((d.facing or "").lower())
        if vec is None:
            return 1.0
        dot = vec[0] * nx + vec[1] * ny
        return -1.0 if dot < -1e-6 else 1.0

    def _oneway_arrow(
        self, cx: float, cy: float, ux: float, uy: float,
        nx: float, ny: float, s: float,
    ) -> str:
        """A small arrow across the opening (along the wall normal) marking the
        allowed direction of travel."""
        tip = (cx + s * 0.3 * nx, cy + s * 0.3 * ny)
        back = (cx - s * 0.3 * nx, cy - s * 0.3 * ny)
        b1 = (tip[0] - s * 0.16 * nx + 0.13 * ux, tip[1] - s * 0.16 * ny + 0.13 * uy)
        b2 = (tip[0] - s * 0.16 * nx - 0.13 * ux, tip[1] - s * 0.16 * ny - 0.13 * uy)
        return (
            self._line_to_svg(LineWall(back, tip), cls="door")
            + self._line_to_svg(LineWall(tip, b1), cls="door")
            + self._line_to_svg(LineWall(tip, b2), cls="door")
        )

    # --- door sub-glyphs ---

    def _jamb_ticks(
        self,
        cx: float,
        cy: float,
        ux: float,
        uy: float,
        nx: float,
        ny: float,
        half: float,
        tick: float,
    ) -> str:
        out: list[str] = []
        for sign in (-1, 1):
            px = cx + sign * half * ux
            py = cy + sign * half * uy
            tx, ty = nx * tick, ny * tick
            out.append(
                self._line_to_svg(
                    LineWall((px - tx, py - ty), (px + tx, py + ty)),
                    cls="door",
                )
            )
        return "".join(out)

    def _debris_marks(
        self,
        cx: float,
        cy: float,
        ux: float,
        uy: float,
        nx: float,
        ny: float,
        half: float,
    ) -> str:
        """Scattered rubble chunks around a smashed door — short segments
        littering the opening on both sides of the wall. `a` runs along the
        wall, `p` across it; `(du, dn)` orients each chunk."""
        marks = [
            (0.06, 0.30, 1.0, 0.4),
            (-0.16, 0.40, 0.3, 1.0),
            (0.26, -0.32, -0.8, 0.6),
            (-0.28, -0.26, 1.0, -0.3),
            (0.34, 0.20, 0.5, 0.9),
            (-0.04, -0.42, -0.6, -0.8),
        ]
        chunk = 0.08
        out: list[str] = []
        for a, p, du, dn in marks:
            mx = cx + a * half * 2 * ux + p * nx
            my = cy + a * half * 2 * uy + p * ny
            dvx = du * ux + dn * nx
            dvy = du * uy + dn * ny
            dl = (dvx * dvx + dvy * dvy) ** 0.5 or 1.0
            dvx, dvy = dvx / dl * chunk, dvy / dl * chunk
            out.append(
                self._line_to_svg(
                    LineWall((mx - dvx, my - dvy), (mx + dvx, my + dvy)),
                    cls="door",
                )
            )
        return "".join(out)

    def _closed_leaf(
        self,
        cx: float,
        cy: float,
        ux: float,
        uy: float,
        nx: float,
        ny: float,
        half: float,
    ) -> str:
        """Solid leaf parallel to the wall, between the two jambs."""
        leaf_half = max(half - 0.14, half * 0.55)
        perp = 0.16
        corners = [
            (cx - leaf_half * ux - perp * nx, cy - leaf_half * uy - perp * ny),
            (cx + leaf_half * ux - perp * nx, cy + leaf_half * uy - perp * ny),
            (cx + leaf_half * ux + perp * nx, cy + leaf_half * uy + perp * ny),
            (cx - leaf_half * ux + perp * nx, cy - leaf_half * uy + perp * ny),
        ]
        pts = " ".join(
            f"{_n(p[0])},{_n(self.y(p[1]))}" for p in corners
        )
        return (
            f'<polygon class="door-leaf" points="{pts}" '
            f'fill="#111" stroke="none"/>'
        )

    def _lock_dot(self, cx: float, cy: float) -> str:
        """Small light dot on the leaf — keyhole indicator."""
        return (
            f'<circle class="door-lock" cx="{_n(cx)}" cy="{_n(self.y(cy))}" '
            f'r="0.07" fill="{self._floor_fill()}" stroke="none"/>'
        )

    def _trap_mark(
        self,
        cx: float,
        cy: float,
        ux: float,
        uy: float,
        nx: float,
        ny: float,
    ) -> str:
        """Small X across the leaf centre — trap warning."""
        arm = 0.13
        p1 = (cx - arm * ux - arm * nx, cy - arm * uy - arm * ny)
        p2 = (cx + arm * ux + arm * nx, cy + arm * uy + arm * ny)
        p3 = (cx - arm * ux + arm * nx, cy - arm * uy + arm * ny)
        p4 = (cx + arm * ux - arm * nx, cy + arm * uy - arm * ny)
        cls = 'class="door-trap" stroke="#fafafa" stroke-width="0.06" fill="none"'
        return (
            f'<line {cls} x1="{_n(p1[0])}" y1="{_n(self.y(p1[1]))}" '
            f'x2="{_n(p2[0])}" y2="{_n(self.y(p2[1]))}"/>'
            f'<line {cls} x1="{_n(p3[0])}" y1="{_n(self.y(p3[1]))}" '
            f'x2="{_n(p4[0])}" y2="{_n(self.y(p4[1]))}"/>'
        )

    def _portcullis_symbol(
        self,
        cx: float,
        cy: float,
        ux: float,
        uy: float,
        nx: float,
        ny: float,
        half: float,
    ) -> str:
        """Two rails along the wall with evenly spaced vertical bars."""
        perp = 0.18
        # Two rails parallel to the wall.
        top = LineWall(
            (cx - half * ux + perp * nx, cy - half * uy + perp * ny),
            (cx + half * ux + perp * nx, cy + half * uy + perp * ny),
        )
        bot = LineWall(
            (cx - half * ux - perp * nx, cy - half * uy - perp * ny),
            (cx + half * ux - perp * nx, cy + half * uy - perp * ny),
        )
        parts = [
            self._line_to_svg(top, cls="door"),
            self._line_to_svg(bot, cls="door"),
        ]
        # Vertical bars across the rails. Aim for ~0.35-world-unit spacing.
        n_bars = max(3, int(round(2 * half / 0.35)))
        for i in range(1, n_bars):
            t = -1.0 + 2.0 * i / n_bars
            mx = cx + t * half * ux
            my = cy + t * half * uy
            parts.append(
                self._line_to_svg(
                    LineWall(
                        (mx + perp * nx, my + perp * ny),
                        (mx - perp * nx, my - perp * ny),
                    ),
                    cls="door",
                )
            )
        return "".join(parts)

    def _gates_symbol(
        self,
        cx: float,
        cy: float,
        ux: float,
        uy: float,
        nx: float,
        ny: float,
        half: float,
    ) -> str:
        """A gate: ``-)(-`` — jamb ticks with two arcs that bow toward the
        centre of the opening (the gate's leaves)."""
        r = half * 0.58  # arc half-height (across the wall normal)
        bulge = half * 0.5  # how far each arc bows toward the centre
        plx, ply = cx - half * ux, cy - half * uy  # left jamb
        prx, pry = cx + half * ux, cy + half * uy  # right jamb
        left = self._three_point_arc_path(
            (plx + r * nx, ply + r * ny),
            (plx + bulge * ux, ply + bulge * uy),
            (plx - r * nx, ply - r * ny),
        )
        right = self._three_point_arc_path(
            (prx + r * nx, pry + r * ny),
            (prx - bulge * ux, pry - bulge * uy),
            (prx - r * nx, pry - r * ny),
        )
        return (
            self._jamb_ticks(cx, cy, ux, uy, nx, ny, half, 0.18)
            + f'<path class="door" fill="none" d="{left}"/>'
            + f'<path class="door" fill="none" d="{right}"/>'
        )

    def _open_swing(
        self,
        cx: float,
        cy: float,
        ux: float,
        uy: float,
        nx: float,
        ny: float,
        half: float,
    ) -> str:
        """Door pivoted on the -u jamb, swung 90° in the +n direction.

        Draws the open leaf as a solid line from the pivot to the open
        tip, plus a light dashed arc tracing the swing.
        """
        pivot = (cx - half * ux, cy - half * uy)
        open_tip = (pivot[0] + 2 * half * nx, pivot[1] + 2 * half * ny)
        closed_tip = (cx + half * ux, cy + half * uy)
        # Leaf in the open position.
        leaf = self._line_to_svg(LineWall(pivot, open_tip), cls="door")
        # Quarter-arc from closed_tip to open_tip with via on the diagonal.
        diag = 0.7071  # cos/sin 45°
        via = (
            pivot[0] + 2 * half * (diag * ux + diag * nx),
            pivot[1] + 2 * half * (diag * uy + diag * ny),
        )
        arc_d = self._three_point_arc_path(closed_tip, via, open_tip)
        arc = (
            f'<path class="door-swing" d="{arc_d}" fill="none" '
            f'stroke="#111" stroke-width="{_n(DOOR_STROKE * 0.7)}" '
            f'stroke-dasharray="0.18,0.12"/>'
        )
        return leaf + arc

    # --- legend ---

    def _legend_strip(self) -> str:
        """Symbol legend rendered below the map.

        Lives at SVG y in `[H, H + LEGEND_HEIGHT]` — outside world-y space,
        so y-flip never applies. Each cell shows a short wall segment with
        the door/window glyph centred on it, plus an italic caption.
        """
        entries: list[tuple[str, str, str]] = [
            # (caption, type, state)
            ("Opening", "open", "closed"),
            ("Archway", "arch", "closed"),
            ("Portcullis", "portcullis", "closed"),
            ("Door", "wooden", "closed"),
            ("Double", "double", "closed"),
            ("One-way", "one-way", "closed"),
            ("Locked", "wooden", "locked"),
            ("Trapped", "wooden", "trapped"),
            ("Open", "wooden", "open"),
            ("Secret", "secret", "closed"),
            ("Window", "window", "closed"),
        ]
        n = len(entries)
        top = self.H  # SVG-y of the top edge of the legend strip
        cell_w = self.W / n
        # Door glyph width scales with the cell so symbols stay readable
        # whether the map is 30 or 100 units wide. Capped so big maps
        # don't get cartoonishly huge doors.
        door_w = min(cell_w * 0.32, 1.8)
        symbol_cy = top + 1.6
        caption_cy = top + 2.95
        parts = ['<g class="legend">']
        # Hairline separator across the top of the legend strip.
        parts.append(
            f'<line x1="0" y1="{_n(top + 0.05)}" '
            f'x2="{_n(self.W)}" y2="{_n(top + 0.05)}" '
            f'stroke="#999" stroke-width="0.05"/>'
        )
        for i, (caption, dtype, dstate) in enumerate(entries):
            cx = (i + 0.5) * cell_w
            parts.append(self._legend_cell(cx, symbol_cy, door_w, dtype, dstate))
            parts.append(
                f'<text x="{_n(cx)}" y="{_n(caption_cy)}" '
                f'font-family="Georgia,serif" font-style="italic" '
                f'font-size="0.65" fill="#111" '
                f'text-anchor="middle" dominant-baseline="central">'
                f'{escape(caption)}</text>'
            )
        parts.append("</g>")
        return "\n".join(parts)

    def _legend_cell(
        self,
        cx: float,
        cy: float,
        door_w: float,
        dtype: str,
        dstate: str,
    ) -> str:
        """One legend cell: short horizontal wall + glyph centred on it."""
        half = door_w / 2
        wall_half = door_w * 1.15 + 0.5
        # Wall segment(s). Secret has no gap; everything else cuts a gap
        # the same width as the door symbol.
        if dtype == "secret":
            wall = (
                f'<line class="wall" x1="{_n(cx - wall_half)}" y1="{_n(cy)}" '
                f'x2="{_n(cx + wall_half)}" y2="{_n(cy)}"/>'
            )
        else:
            wall = (
                f'<line class="wall" x1="{_n(cx - wall_half)}" y1="{_n(cy)}" '
                f'x2="{_n(cx - half)}" y2="{_n(cy)}"/>'
                f'<line class="wall" x1="{_n(cx + half)}" y1="{_n(cy)}" '
                f'x2="{_n(cx + wall_half)}" y2="{_n(cy)}"/>'
            )
        return wall + self._legend_symbol(cx, cy, half, dtype, dstate)

    def _legend_symbol(
        self,
        cx: float,
        cy: float,
        half: float,
        dtype: str,
        dstate: str,
    ) -> str:
        """Door / window glyph drawn directly in SVG coords (no y-flip).

        Mirrors the in-map glyphs (`_door_leaf` and `_window`) but with a
        fixed orientation: wall is horizontal (+x), perpendicular is +y.
        """
        if dtype == "window":
            inset = WINDOW_INSET
            return (
                f'<line class="window" '
                f'x1="{_n(cx - half)}" y1="{_n(cy - inset)}" '
                f'x2="{_n(cx + half)}" y2="{_n(cy - inset)}"/>'
                f'<line class="window" '
                f'x1="{_n(cx - half)}" y1="{_n(cy + inset)}" '
                f'x2="{_n(cx + half)}" y2="{_n(cy + inset)}"/>'
            )

        dtype_l = (dtype or "wooden").lower()
        if dtype_l in ("arch", "archway"):
            return self._legend_jambs(cx, cy, half, 0.22)
        if dtype_l == "portcullis":
            return self._legend_portcullis(cx, cy, half)
        if dtype_l == "secret":
            return (
                f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="0.42" '
                f'fill="{self._floor_fill()}" stroke="#111" '
                f'stroke-width="{_n(DOOR_STROKE)}"/>'
                f'<text x="{_n(cx)}" y="{_n(cy)}" '
                f'font-family="Georgia,serif" font-size="0.62" '
                f'font-weight="bold" fill="#111" '
                f'text-anchor="middle" dominant-baseline="central">S</text>'
            )

        parts = [self._legend_jambs(cx, cy, half, 0.18)]
        state = (dstate or "closed").lower()
        if state == "open":
            parts.append(self._legend_open_swing(cx, cy, half))
        else:
            parts.append(self._legend_closed_leaf(cx, cy, half))
            if state == "locked":
                parts.append(
                    f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="0.07" '
                    f'fill="{self._floor_fill()}" stroke="none"/>'
                )
            elif state == "trapped":
                arm = 0.13
                parts.append(
                    f'<line stroke="{self._floor_fill()}" stroke-width="0.06" '
                    f'x1="{_n(cx - arm)}" y1="{_n(cy - arm)}" '
                    f'x2="{_n(cx + arm)}" y2="{_n(cy + arm)}"/>'
                    f'<line stroke="{self._floor_fill()}" stroke-width="0.06" '
                    f'x1="{_n(cx - arm)}" y1="{_n(cy + arm)}" '
                    f'x2="{_n(cx + arm)}" y2="{_n(cy - arm)}"/>'
                )
        return "".join(parts)

    def _legend_jambs(self, cx: float, cy: float, half: float, tick: float) -> str:
        return (
            f'<line class="door" x1="{_n(cx - half)}" y1="{_n(cy - tick)}" '
            f'x2="{_n(cx - half)}" y2="{_n(cy + tick)}"/>'
            f'<line class="door" x1="{_n(cx + half)}" y1="{_n(cy - tick)}" '
            f'x2="{_n(cx + half)}" y2="{_n(cy + tick)}"/>'
        )

    def _legend_closed_leaf(self, cx: float, cy: float, half: float) -> str:
        leaf_half = max(half - 0.14, half * 0.55)
        perp = 0.16
        return (
            f'<rect class="door-leaf" '
            f'x="{_n(cx - leaf_half)}" y="{_n(cy - perp)}" '
            f'width="{_n(2 * leaf_half)}" height="{_n(2 * perp)}" '
            f'fill="#111" stroke="none"/>'
        )

    def _legend_portcullis(self, cx: float, cy: float, half: float) -> str:
        perp = 0.18
        parts = [
            f'<line class="door" x1="{_n(cx - half)}" y1="{_n(cy - perp)}" '
            f'x2="{_n(cx + half)}" y2="{_n(cy - perp)}"/>',
            f'<line class="door" x1="{_n(cx - half)}" y1="{_n(cy + perp)}" '
            f'x2="{_n(cx + half)}" y2="{_n(cy + perp)}"/>',
        ]
        n_bars = max(3, int(round(2 * half / 0.35)))
        for i in range(1, n_bars):
            t = -1.0 + 2.0 * i / n_bars
            mx = cx + t * half
            parts.append(
                f'<line class="door" x1="{_n(mx)}" y1="{_n(cy - perp)}" '
                f'x2="{_n(mx)}" y2="{_n(cy + perp)}"/>'
            )
        return "".join(parts)

    def _legend_open_swing(self, cx: float, cy: float, half: float) -> str:
        """Door pivoted on left jamb, swung 90° downward (into the legend row)."""
        pivot_x = cx - half
        open_tip_x = pivot_x
        open_tip_y = cy + 2 * half
        closed_tip_x = cx + half
        radius = 2 * half
        leaf = (
            f'<line class="door" x1="{_n(pivot_x)}" y1="{_n(cy)}" '
            f'x2="{_n(open_tip_x)}" y2="{_n(open_tip_y)}"/>'
        )
        # SVG arc: closed_tip(cx+half, cy) → open_tip(cx-half, cy+2*half),
        # radius=2*half, sweep-flag=1 (clockwise in SVG y-down space).
        arc = (
            f'<path class="door-swing" d="M {_n(closed_tip_x)} {_n(cy)} '
            f'A {_n(radius)} {_n(radius)} 0 0 1 '
            f'{_n(open_tip_x)} {_n(open_tip_y)}" '
            f'fill="none" stroke="#111" '
            f'stroke-width="{_n(DOOR_STROKE * 0.7)}" '
            f'stroke-dasharray="0.18,0.12"/>'
        )
        return leaf + arc

    def _wrap_door(self, d: Door, body: str) -> str:
        """Wrap door SVG in a <g> carrying data-* attributes for tooltips
        and the print/PDF view. The label is only attached when there's
        something to say (description or dm_notes) so plain doors don't
        clutter the hover UI.
        """
        attrs = f'class="door-instance" data-door="{escape(d.type)}"'
        if d.description or d.dm_notes:
            bits: list[str] = []
            if d.state and d.state not in ("closed", ""):
                bits.append(d.state)
            if d.type and d.type not in ("wooden", ""):
                bits.append(d.type)
            dtype = (d.type or "").lower()
            if dtype in ("arch", "archway"):
                kind = "archway"
            elif dtype == "portcullis":
                kind = "portcullis"
            else:
                kind = "door"
            label = " ".join(bits + [kind]).capitalize() or "Door"
            attrs += f' data-label="{escape(label)}"'
        if d.description:
            attrs += f' data-description="{escape(d.description)}"'
        if d.dm_notes:
            attrs += f' data-dm-notes="{escape(d.dm_notes)}"'
        return f"<g {attrs}>{body}</g>"

    def _marker_door_symbol(
        self,
        d: Door,
        wall_info: tuple[LineWall, float] | None,
        letter: str,
        kind: str,
    ) -> str:
        """Small letter-in-circle marker drawn on top of the wall — no gap.
        Used for `secret` ("S") and `concealed` ("C") doors."""
        if wall_info is None:
            px, py = d.position
        else:
            wall, t = wall_info
            ax, ay = wall.a
            bx, by = wall.b
            dx, dy = bx - ax, by - ay
            px = ax + t * dx
            py = ay + t * dy
        radius = 0.42
        return (
            f'<g class="door {kind}-door" data-door="{kind}">'
            f'<circle cx="{_n(px)}" cy="{_n(self.y(py))}" '
            f'r="{_n(radius)}" fill="{self._floor_fill()}" '
            f'stroke="#111" stroke-width="{_n(DOOR_STROKE)}"/>'
            f'<text x="{_n(px)}" y="{_n(self.y(py))}" '
            f'font-family="Georgia,serif" font-size="0.62" '
            f'font-weight="bold" fill="#111" '
            f'text-anchor="middle" dominant-baseline="central">{letter}</text>'
            f"</g>"
        )

    def _find_door_wall(self, d: Door) -> tuple[LineWall, float] | None:
        """Locate the wall this door sits on. Searches across all rooms."""
        best: tuple[LineWall, float, float] | None = None
        for r in self.all_rooms.values():
            for w in room_walls(r):
                if not isinstance(w, LineWall):
                    continue
                _, t, dist = project_onto_wall(d.position, w)
                if best is None or dist < best[2]:
                    best = (w, t, dist)
        if best is None or best[2] > 1.0:
            return None
        return best[0], best[1]

    def _window(self, w: Window) -> str:
        room = self.all_rooms.get(_strip_kind(w.in_ref))
        if room is None:
            return ""
        best: tuple[LineWall, float, float] | None = None
        for wall in room_walls(room):
            if not isinstance(wall, LineWall):
                continue
            _, t, dist = project_onto_wall(w.position, wall)
            if best is None or dist < best[2]:
                best = (wall, t, dist)
        if best is None or best[2] > 0.5:
            return ""
        wall, t, _ = best
        ax, ay = wall.a
        bx, by = wall.b
        dx, dy = bx - ax, by - ay
        L = (dx * dx + dy * dy) ** 0.5 or 1.0
        ux, uy = dx / L, dy / L
        nx, ny = -uy, ux
        cx = ax + t * dx
        cy = ay + t * dy
        half = w.width / 2.0
        s1 = (cx - half * ux, cy - half * uy)
        e1 = (cx + half * ux, cy + half * uy)
        s2 = (s1[0] + nx * WINDOW_INSET, s1[1] + ny * WINDOW_INSET)
        e2 = (e1[0] + nx * WINDOW_INSET, e1[1] + ny * WINDOW_INSET)
        s3 = (s1[0] - nx * WINDOW_INSET, s1[1] - ny * WINDOW_INSET)
        e3 = (e1[0] - nx * WINDOW_INSET, e1[1] - ny * WINDOW_INSET)
        return (
            self._line_to_svg(LineWall(s2, e2), cls="window")
            + self._line_to_svg(LineWall(s3, e3), cls="window")
        )

    # --- markers ---

    def _marker(self, m: Marker) -> str:
        """Token-style indicator at a single point. Colour comes from the
        palette (or a CSS literal); the initial letter is drawn in
        contrasting white."""
        cx, cy = m.position
        sy = self.y(cy)
        radius = max(m.size, 0.18)
        # Resolve colour: palette key takes priority; otherwise pass-through.
        tag = m.tag or MARKER_DEFAULT_TAG
        fill = MARKER_PALETTE.get(tag, tag)
        initial = (m.initial or (m.name[:1] if m.name else "?")).upper()[:2]
        # Outer ring slightly darker than the fill so the token reads on
        # any background — same trick the legend uses for door leaves.
        # SVG doesn't natively darken a colour string, but a translucent
        # black stroke achieves the same effect cheaply.
        stroke = "#111"
        attrs = f'class="marker" data-name="{escape(m.name)}" data-tag="{escape(tag)}"'
        if m.location:
            attrs += f' data-location="{escape(m.location)}"'
        if m.description:
            attrs += f' data-description="{escape(m.description)}"'
        if m.dm_notes:
            attrs += f' data-dm-notes="{escape(m.dm_notes)}"'
        font = _n(radius * 1.05)
        parts = [f"<g {attrs}>"]
        if m.image:
            # Image token: a colored ring (using the tag fill as border) holds
            # an <image> clipped to a circle. The initial glyph is suppressed
            # since the portrait takes its place. Clip id mixes name and
            # position so multiple tokens with the same name don't collide.
            clip_id = (
                f"marker-clip-{_slug(m.name)}-"
                f"{_slug(_n(cx))}-{_slug(_n(sy))}"
            )
            img_size = radius * 2
            parts.append(
                f'<defs><clipPath id="{clip_id}">'
                f'<circle cx="{_n(cx)}" cy="{_n(sy)}" r="{_n(radius)}"/>'
                f"</clipPath></defs>"
            )
            parts.append(
                f'<image href="{escape(m.image)}" '
                f'x="{_n(cx - radius)}" y="{_n(sy - radius)}" '
                f'width="{_n(img_size)}" height="{_n(img_size)}" '
                f'preserveAspectRatio="xMidYMid slice" '
                f'clip-path="url(#{clip_id})"/>'
            )
            parts.append(
                f'<circle cx="{_n(cx)}" cy="{_n(sy)}" r="{_n(radius)}" '
                f'fill="none" stroke="{fill}" '
                f'stroke-width="{_n(radius * 0.22)}"/>'
            )
            parts.append(
                f'<circle cx="{_n(cx)}" cy="{_n(sy)}" r="{_n(radius)}" '
                f'fill="none" stroke="{stroke}" '
                f'stroke-width="{_n(radius * 0.08)}"/>'
            )
        else:
            parts.append(
                f'<circle cx="{_n(cx)}" cy="{_n(sy)}" r="{_n(radius)}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="{_n(radius * 0.18)}"/>'
            )
            parts.append(
                f'<text x="{_n(cx)}" y="{_n(sy)}" '
                f'font-family="Georgia,serif" font-weight="bold" '
                f'font-size="{font}" fill="#fff" '
                f'text-anchor="middle" dominant-baseline="central">'
                f"{escape(initial)}</text>"
            )
        # Optional small caption directly below the token. We use the
        # explicit label override if set; we DON'T auto-emit the bare
        # name because most maps end up with overlapping tokens that get
        # noisy with always-on labels.
        if m.label:
            caption_y = sy + radius * 1.85
            parts.append(
                f'<text x="{_n(cx)}" y="{_n(caption_y)}" '
                f'font-family="Georgia,serif" font-style="italic" '
                f'font-size="{_n(radius * 0.95)}" fill="#111" '
                f'text-anchor="middle" dominant-baseline="hanging" '
                f'paint-order="stroke" stroke="{self._floor_fill()}" '
                f'stroke-width="{_n(radius * 0.2)}" stroke-linejoin="round">'
                f"{escape(m.label)}</text>"
            )
        parts.append("</g>")
        return "".join(parts)

    # --- features ---

    def _feature(self, fi: FeatureInstance) -> str:
        fd = self.dmap.feature_defs.get(fi.ref)
        if fd is not None:
            body = self._render_feature_def(fd)
            display_label = fd.display_name or _humanize(fi.ref)
        else:
            # Built-ins live in `core.dmap` (brought in via `include`), so
            # a miss here means an undefined feature. Validate flags it;
            # render a placeholder so the output stays well-formed.
            body = _generic_glyph("?")
            display_label = fi.ref
        x, y = fi.position
        sx = fi.scale
        sy = fi.scale if fi.scale_y is None else fi.scale_y  # uniform when unset
        if self.flip_y:
            # Mirror the local frame so the glyph isn't drawn upside down.
            transform = (
                f"translate({_n(x)},{_n(self.y(y))}) "
                f"scale({_n(sx)},{_n(-sy)}) "
                f"rotate({_n(-fi.rotate)})"
            )
        else:
            transform = (
                f"translate({_n(x)},{_n(y)}) "
                f"scale({_n(sx)},{_n(sy)}) rotate({_n(fi.rotate)})"
            )
        attrs = (
            f'class="feature-instance" data-ref="{escape(fi.ref)}" '
            f'data-label="{escape(display_label)}" '
            f'transform="{transform}"'
        )
        if fi.description:
            attrs += f' data-description="{escape(fi.description)}"'
        if fi.dm_notes:
            attrs += f' data-dm-notes="{escape(fi.dm_notes)}"'
        return f"<g {attrs}>{body}</g>"

    def _render_feature_def(self, fd: FeatureDef) -> str:
        if fd.glyph:
            return "".join(self._glyph_svg(g) for g in fd.glyph)
        parts = [self._shape_svg(fd.shape, fd.background, fd.outline)]
        for ov in fd.overlays:
            parts.append(self._overlay_svg(ov))
        return "".join(parts)

    def _glyph_svg(self, g) -> str:  # type: ignore[no-untyped-def]
        cls = {"stroke": "feature", "fill": "feature-fill", "plain": None}[g.role]
        classes = " ".join(c for c in (cls, g.extra_class) if c)
        head = f' class="{classes}"' if classes else ""
        tail = ""
        if g.fill is not None:
            tail += f' fill="{g.fill}"'
        if g.stroke is not None:
            tail += f' stroke="{g.stroke}"'
        if g.stroke_width is not None:
            tail += f' stroke-width="{_n(g.stroke_width)}"'
        if isinstance(g, GlyphCircle):
            return f'<circle{head} cx="{_n(g.cx)}" cy="{_n(g.cy)}" r="{_n(g.r)}"{tail}/>'
        if isinstance(g, GlyphRect):
            rx = f' rx="{_n(g.rx)}"' if g.rx is not None else ""
            return (
                f'<rect{head} x="{_n(g.x)}" y="{_n(g.y)}" '
                f'width="{_n(g.width)}" height="{_n(g.height)}"{rx}{tail}/>'
            )
        if isinstance(g, GlyphLine):
            return (
                f'<line{head} x1="{_n(g.x1)}" y1="{_n(g.y1)}" '
                f'x2="{_n(g.x2)}" y2="{_n(g.y2)}"{tail}/>'
            )
        if isinstance(g, GlyphPolygon):
            pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in g.points)
            return f'<polygon{head} points="{pts}"{tail}/>'
        if isinstance(g, GlyphPolyline):
            pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in g.points)
            return f'<polyline{head} points="{pts}"{tail}/>'
        if isinstance(g, GlyphPath):
            return f'<path{head} d="{g.d}"{tail}/>'
        return ""

    def _shape_svg(self, shape, background, outline) -> str:  # type: ignore[no-untyped-def]
        fill = background or "#ffffff"
        stroke = (outline.color if outline else None) or "#111"
        sw = (outline.width if outline else None) or FEATURE_STROKE
        dash = ""
        if outline and outline.stroke == "dashed":
            dash = f' stroke-dasharray="{_n(sw * 3)},{_n(sw * 2)}"'
        if isinstance(shape, CircleShape):
            return (
                f'<circle cx="0" cy="0" r="{_n(shape.radius)}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="{_n(sw)}"{dash}/>'
            )
        if isinstance(shape, RectShape):
            w, h = shape.width, shape.height
            return (
                f'<rect x="{_n(-w / 2)}" y="{_n(-h / 2)}" width="{_n(w)}" '
                f'height="{_n(h)}" fill="{fill}" stroke="{stroke}" '
                f'stroke-width="{_n(sw)}"{dash}/>'
            )
        if isinstance(shape, PolygonShape):
            pts = " ".join(f"{_n(p[0])},{_n(p[1])}" for p in shape.points)
            return (
                f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" '
                f'stroke-width="{_n(sw)}"{dash}/>'
            )
        return ""

    def _overlay_svg(self, ov: Overlay) -> str:
        ox, oy = ov.offset
        fill = ov.fill or "#111"
        if isinstance(ov.shape, CircleShape):
            return (
                f'<circle cx="{_n(ox)}" cy="{_n(oy)}" r="{_n(ov.shape.radius)}" '
                f'fill="{fill}"/>'
            )
        if isinstance(ov.shape, RectShape):
            w, h = ov.shape.width, ov.shape.height
            return (
                f'<rect x="{_n(ox - w / 2)}" y="{_n(oy - h / 2)}" '
                f'width="{_n(w)}" height="{_n(h)}" fill="{fill}"/>'
            )
        if isinstance(ov.shape, PolygonShape):
            pts = " ".join(
                f"{_n(p[0] + ox)},{_n(p[1] + oy)}" for p in ov.shape.points
            )
            return f'<polygon points="{pts}" fill="{fill}"/>'
        return ""

    # --- labels ---

    def _map_title(self) -> str:
        """On-map title, positioned with the same align logic as labels but
        against the full map bbox; defaults to top-centre."""
        t = self.dmap.map.title
        if t is None or not t.text:
            return ""
        bbox = (0.0, 0.0, self.W, self.H)
        if t.position is not None:
            x, y = t.position
            anchor_h, baseline = "middle", "central"
        else:
            x, y, anchor_h, baseline = self._label_anchor_from_align(
                bbox, t.align_v or "top", t.align_h or "center"
            )
        size = LABEL_BASE_SIZE * 2.0 * t.size
        text = escape(t.text)
        if self.flip_y:
            transform = (
                f"translate({_n(x)},{_n(self.y(y))}) "
                f"rotate({_n(-t.rotate)}) scale(1,-1)"
            )
        else:
            transform = f"translate({_n(x)},{_n(y)}) rotate({_n(t.rotate)})"
        return (
            f'<text class="map-title" transform="{transform}" '
            f'text-anchor="{anchor_h}" dominant-baseline="{baseline}" '
            f'font-size="{_n(size)}" font-family="Georgia,serif" '
            f'font-weight="700" fill="#111">{text}</text>'
        )

    def _text_annotation(self, ta: TextAnnotation) -> str:
        """Render a freestanding text annotation at its fixed world position.

        Centered on the anchor point; `size` scales the base label size,
        matching how a room label's `size` works. Honours flip-y so the text
        isn't mirrored on bottom-left-origin maps."""
        x, y = ta.position
        size = LABEL_BASE_SIZE * ta.size
        text = escape(ta.text)
        if self.flip_y:
            transform = (
                f"translate({_n(x)},{_n(self.y(y))}) "
                f"rotate({_n(-ta.rotate)}) scale(1,-1)"
            )
        else:
            transform = f"translate({_n(x)},{_n(y)}) rotate({_n(ta.rotate)})"
        attrs = 'class="label text-annotation"'
        if ta.description:
            attrs += f' data-description="{escape(ta.description)}"'
        if ta.dm_notes:
            attrs += f' data-dm-notes="{escape(ta.dm_notes)}"'
        return (
            f'<text {attrs} transform="{transform}" '
            f'text-anchor="middle" dominant-baseline="central" '
            f'font-size="{_n(size)}">{text}</text>'
        )

    def _room_label(self, r: Room) -> str:
        label = r.label
        if label is None:
            return ""
        # Default anchor (used when the label has neither `at` nor `align`):
        # centered on the room's centroid + middle/central anchors.
        anchor_h = "middle"
        baseline = "central"
        if label.position is not None:
            x, y = label.position
        elif label.align_v is not None or label.align_h is not None:
            x, y, anchor_h, baseline = self._label_anchor_from_align(
                self._room_bbox(r), label.align_v, label.align_h
            )
        else:
            x, y = _room_centroid(r)
        size = LABEL_BASE_SIZE * label.size
        number = self.room_numbers.get(r.name)
        prefix = (
            f"{number}. "
            if number is not None and self.dmap.map.room_numbers
            else ""
        )
        text = escape(prefix + label.text)
        # In flipped-y mode we counter-flip so text isn't mirrored.
        if self.flip_y:
            transform = (
                f"translate({_n(x)},{_n(self.y(y))}) "
                f"rotate({_n(-label.rotate)}) scale(1,-1)"
            )
        else:
            transform = (
                f"translate({_n(x)},{_n(y)}) rotate({_n(label.rotate)})"
            )
        return (
            f'<text class="label" transform="{transform}" '
            f'text-anchor="{anchor_h}" dominant-baseline="{baseline}" '
            f'font-size="{_n(size)}">{text}</text>'
        )

    def _label_anchor_from_align(
        self,
        bbox: tuple[float, float, float, float],
        v: str | None,
        h: str | None,
    ) -> tuple[float, float, str, str]:
        """Return (world_x, world_y, text-anchor, dominant-baseline) for an
        align-based label, anchored inside `bbox` with a small inset so
        text doesn't kiss the boundary.

        v ∈ {top, middle, bottom, None=middle}; h ∈ {left, center, right,
        None=center}. The y position is in world coords (the caller applies
        the SVG y-flip). In flip-y mode the baseline keyword is swapped so
        that "top" / "bottom" remain visually correct after `scale(1,-1)`.
        """
        v = v or "middle"
        h = h or "center"
        min_x, min_y, max_x, max_y = bbox
        pad = LABEL_INSET
        if h == "left":
            x, anchor = min_x + pad, "start"
        elif h == "right":
            x, anchor = max_x - pad, "end"
        else:
            x, anchor = (min_x + max_x) / 2.0, "middle"
        # Visual top corresponds to higher world y in flip-y mode, lower
        # otherwise. Keep the position in world coords; the caller flips.
        if v == "top":
            y = (max_y - pad) if self.flip_y else (min_y + pad)
            # After scale(1,-1) in flip-y, the SVG baselines invert.
            baseline = "alphabetic" if self.flip_y else "hanging"
        elif v == "bottom":
            y = (min_y + pad) if self.flip_y else (max_y - pad)
            baseline = "hanging" if self.flip_y else "alphabetic"
        else:
            y = (min_y + max_y) / 2.0
            baseline = "central"
        return x, y, anchor, baseline

    # --- low-level svg helpers ---

    def _line_to_svg(self, w: LineWall, cls: str = "wall") -> str:
        x1, y1 = w.a
        x2, y2 = w.b
        return (
            f'<line class="{cls}" x1="{_n(x1)}" y1="{_n(self.y(y1))}" '
            f'x2="{_n(x2)}" y2="{_n(self.y(y2))}"/>'
        )

    def _trail_marks(self, w: LineWall) -> str:
        """`line_style trail` — x-marks evenly spaced along a wall."""
        return self._trail_marks_between(w.a, w.b)

    def _trail_marks_between(self, a: Vec2, b: Vec2) -> str:
        """Small x-marks evenly spaced along the segment a→b, centred in
        each step so the ends aren't clipped. Shared by room walls and
        zero-width (single-line) corridors."""
        x1, y1 = a
        x2, y2 = b
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            return ""
        ux, uy = dx / length, dy / length
        n = max(1, round(length / TRAIL_SPACING))
        step = length / n
        r = TRAIL_MARK
        out: list[str] = []
        for i in range(n):
            cx = x1 + ux * (i + 0.5) * step
            cy = self.y(y1 + uy * (i + 0.5) * step)
            out.append(
                f'<path class="trail-x" d="M{_n(cx - r)},{_n(cy - r)} '
                f'L{_n(cx + r)},{_n(cy + r)} M{_n(cx - r)},{_n(cy + r)} '
                f'L{_n(cx + r)},{_n(cy - r)}"/>'
            )
        return "".join(out)

    def _centerline_dash(self, line_style: str | None) -> tuple[str | None, str]:
        """(stroke-dasharray, stroke-linecap) for a single-line corridor's
        `line_style`. Mirrors the room wall dash patterns; trail is handled
        separately (it draws marks, not a dashed stroke)."""
        if line_style == "dotted":
            return (f"0.01,{_n(WALL_STROKE * 1.6)}", "round")
        if line_style == "dashed":
            return (f"{_n(WALL_STROKE * 3)},{_n(WALL_STROKE * 2)}", "butt")
        if line_style == "ruined":
            return (
                f"{_n(WALL_STROKE * 3)},{_n(WALL_STROKE * 1.8)},0.01,"
                f"{_n(WALL_STROKE * 1.8)}",
                "round",
            )
        return (None, "round")

    # --- line features (bars / curtain / barred) ---

    def _all_line_features(self) -> list[LineFeature]:
        """Top-level line features plus those in visible layers."""
        out: list[LineFeature] = list(self.dmap.line_features)
        for layer in self.dmap.layers:
            if not layer.hidden:
                out.extend(layer.line_features)
        return out

    def _polyline_path(self, pts: list[Vec2]) -> str:
        """`M …  L …` through the points (with the vertical flip applied)."""
        return "M " + " L ".join(
            f"{_n(x)},{_n(self.y(y))}" for x, y in pts
        )

    def _line_feature(self, lf: LineFeature) -> str:
        pts = lf.points
        if len(pts) < 2:
            return ""
        kind = (lf.kind or "bars").lower()
        attrs = f'data-line-feature="{escape(lf.name)}" data-kind="{escape(kind)}"'
        if lf.description:
            attrs += f' data-description="{escape(lf.description)}"'
        if lf.dm_notes:
            attrs += f' data-dm-notes="{escape(lf.dm_notes)}"'

        if kind == "barred":
            marks = "".join(
                self._plus_marks_between(a, b) for a, b in zip(pts, pts[1:])
            )
            return f'<g {attrs}>{marks}</g>'
        if kind == "curtain":
            d = self._wavy_path(pts)
        elif kind == "bars":
            # Dotted along the path (round-capped zero-length dashes).
            d = self._polyline_path(pts)
            dash = f' stroke-dasharray="0.01,{_n(LINE_FEATURE_STROKE * 3)}"'
            return f'<path class="line-feature" {attrs} d="{d}"{dash}/>'
        else:
            # Unknown kind: a plain solid line so it still renders.
            d = self._polyline_path(pts)
        return f'<path class="line-feature" {attrs} d="{d}"/>'

    def _wavy_path(self, pts: list[Vec2]) -> str:
        """A continuous sine wiggle along the polyline (the curtain look)."""
        out: list[str] = []
        first = True
        for a, b in zip(pts, pts[1:]):
            x1, y1 = a
            x2, y2 = b
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length <= 1e-9:
                continue
            ux, uy = dx / length, dy / length
            nx, ny = -uy, ux  # perpendicular
            steps = max(2, round(length / (CURTAIN_WAVELEN / 4)))
            for i in range(steps + 1):
                t = i / steps
                off = CURTAIN_AMP * math.sin(t * length / CURTAIN_WAVELEN * 2 * math.pi)
                px = x1 + ux * length * t + nx * off
                py = y1 + uy * length * t + ny * off
                cmd = "M" if first else "L"
                out.append(f"{cmd} {_n(px)},{_n(self.y(py))}")
                first = False
        return " ".join(out)

    def _plus_marks_between(self, a: Vec2, b: Vec2) -> str:
        """Small `+` marks evenly spaced along a→b (the barred look)."""
        x1, y1 = a
        x2, y2 = b
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            return ""
        ux, uy = dx / length, dy / length
        n = max(1, round(length / BARRED_SPACING))
        step = length / n
        r = BARRED_MARK
        out: list[str] = []
        for i in range(n + 1):
            cx = x1 + ux * i * step
            cy = self.y(y1 + uy * i * step)
            out.append(
                f'<path class="line-feature" d="M{_n(cx - r)},{_n(cy)} '
                f'L{_n(cx + r)},{_n(cy)} M{_n(cx)},{_n(cy - r)} '
                f'L{_n(cx)},{_n(cy + r)}"/>'
            )
        return "".join(out)

    def _arc_wall_to_svg(self, w: ArcWall) -> str:
        d = self._three_point_arc_path(w.a, w.via, w.b)
        return f'<path class="wall" d="{d}"/>'

    def _arc_path_segment(self, w: ArcWall) -> str:
        """Like `_three_point_arc_path` but only the suffix (no leading M)."""
        return _arc_polyline_segment(w.a, w.via, w.b, self.y)

    def _three_point_arc_path(self, a: Vec2, via: Vec2, b: Vec2) -> str:
        # Polyline-approximation keeps us out of the SVG arc-flag swamp.
        head = f"M {_n(a[0])},{_n(self.y(a[1]))}"
        tail = _arc_polyline_segment(a, via, b, self.y)
        return f"{head} {tail}"

    def _arc_segment_path(self, s: ArcSegment) -> str:
        """Linearized path tail (no leading M) for a parametric arc."""
        start = _arc_endpoint(s, s.from_angle)
        end = _arc_endpoint(s, s.to_angle)
        steps = max(12, int(abs(s.to_angle - s.from_angle) // 5) + 1)
        cx, cy = s.center
        a0 = math.radians(s.from_angle)
        a1 = math.radians(s.to_angle)
        if s.sweep == "cw" and a1 > a0:
            a1 -= 2 * math.pi
        elif s.sweep == "ccw" and a1 < a0:
            a1 += 2 * math.pi
        parts: list[str] = []
        for i in range(1, steps + 1):
            t = i / steps
            ang = a0 + (a1 - a0) * t
            x = cx + s.radius * math.cos(ang)
            y = cy + s.radius * math.sin(ang)
            parts.append(f"L {_n(x)},{_n(self.y(y))}")
        return " ".join(parts) or f"L {_n(end[0])},{_n(self.y(end[1]))}"


# ----- glyph library (in normalized local coords centered on origin) -----

def _generic_glyph(letter: str) -> str:
    return (
        '<rect class="feature" x="-0.35" y="-0.35" width="0.7" height="0.7" rx="0.06"/>'
        f'<text font-family="Georgia,serif" font-size="0.6" fill="#111" '
        f'text-anchor="middle" dominant-baseline="central">{escape(letter)}</text>'
    )


# ----- free functions -----

def _strip_kind(qualified: str) -> str:
    """Strip a `room.` or `corridor.` prefix and return the bare name."""
    if "." in qualified:
        return qualified.split(".", 1)[1]
    return qualified


def _door_touches_room(d: Door, r: Room) -> bool:
    """True if the door's connects mention this room, OR no connects given.

    A door with no `connects` should still cut whatever wall it sits on.
    """
    if not d.connects:
        return True
    target = f"room.{r.name}"
    return target in d.connects


def _apply_cuts(
    w: LineWall, cuts: list[tuple[float, float]]
) -> list[LineWall]:
    """Apply multiple cuts to a wall. Cuts are along-wall t-intervals."""
    if not cuts:
        return [w]
    # Merge overlapping cuts.
    merged: list[tuple[float, float]] = []
    for lo, hi in sorted(cuts):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    pieces = [w]
    for lo, hi in merged:
        new_pieces: list[LineWall] = []
        for p in pieces:
            # Subdivide each piece by the original-wall parameter. We
            # parameterize each piece on the original wall via its own
            # endpoint t-values.
            t_a = _t_on(w, p.a)
            t_b = _t_on(w, p.b)
            piece_lo = min(t_a, t_b)
            piece_hi = max(t_a, t_b)
            if hi <= piece_lo or lo >= piece_hi:
                new_pieces.append(p)
                continue
            # Convert cut bounds into the piece's local t-space.
            piece_range = piece_hi - piece_lo
            if piece_range <= 0:
                continue
            local_lo = max(0.0, (lo - piece_lo) / piece_range)
            local_hi = min(1.0, (hi - piece_lo) / piece_range)
            new_pieces.extend(cut_wall(p, local_lo, local_hi))
        pieces = new_pieces
    return pieces


def _t_on(w: LineWall, p: Vec2) -> float:
    ax, ay = w.a
    bx, by = w.b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return 0.0
    return ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2


def _room_centroid(r: Room) -> Vec2:
    pts: list[Vec2] = []
    for w in room_walls(r):
        pts.append(w.a)
    if not pts:
        return (0.0, 0.0)
    sx = sum(p[0] for p in pts) / len(pts)
    sy = sum(p[1] for p in pts) / len(pts)
    return (sx, sy)


def _point_segment_dist(p: Vec2, a: Vec2, b: Vec2) -> float:
    """Shortest distance from point `p` to segment `a`-`b`."""
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _line_intersect(p: Vec2, dirv: Vec2, a: Vec2, b: Vec2) -> Vec2 | None:
    """Intersection of the infinite line through `p` with direction `dirv`
    and the infinite line through `a`-`b`. None if the two are (near-)
    parallel."""
    rx, ry = dirv
    sx, sy = b[0] - a[0], b[1] - a[1]
    denom = rx * sy - ry * sx
    if abs(denom) < 1e-9:
        return None
    qx, qy = a[0] - p[0], a[1] - p[1]
    t = (qx * sy - qy * sx) / denom
    return (p[0] + t * rx, p[1] + t * ry)


def _arc_endpoint(s: ArcSegment, angle_deg: float) -> Vec2:
    a = math.radians(angle_deg)
    return (s.center[0] + s.radius * math.cos(a),
            s.center[1] + s.radius * math.sin(a))


def _arc_polyline_segment(a: Vec2, via: Vec2, b: Vec2, y_xform) -> str:  # type: ignore[no-untyped-def]
    """Linearize a 3-point arc into a sequence of SVG line commands."""
    center, radius = _three_point_circle(a, via, b)
    if center is None:
        return f"L {_n(b[0])},{_n(y_xform(b[1]))}"
    cx, cy = center
    θa = math.atan2(a[1] - cy, a[0] - cx)
    θv = math.atan2(via[1] - cy, via[0] - cx)
    θb = math.atan2(b[1] - cy, b[0] - cx)
    # Pick the direction (CCW or CW) such that via lies between start and end.
    sweep_ccw = (θv - θa) % (2 * math.pi)
    sweep_to_end_ccw = (θb - θa) % (2 * math.pi)
    if sweep_ccw <= sweep_to_end_ccw:
        end_offset = sweep_to_end_ccw
        direction = 1.0
    else:
        end_offset = (2 * math.pi) - sweep_to_end_ccw
        direction = -1.0
    steps = max(16, int(math.degrees(end_offset) / 5) + 1)
    parts: list[str] = []
    for i in range(1, steps + 1):
        t = i / steps
        ang = θa + direction * end_offset * t
        x = cx + radius * math.cos(ang)
        y = cy + radius * math.sin(ang)
        parts.append(f"L {_n(x)},{_n(y_xform(y))}")
    return " ".join(parts)


def _three_point_circle(
    a: Vec2, b: Vec2, c: Vec2
) -> tuple[Vec2 | None, float]:
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None, 0.0
    ux = ((ax * ax + ay * ay) * (by - cy)
          + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx)
          + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    r = ((ux - ax) ** 2 + (uy - ay) ** 2) ** 0.5
    return (ux, uy), r


def _n(v: float) -> str:
    """Format a float compactly: trim trailing zeros, drop the `.0`."""
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s or "0"


def _slug(name: str) -> str:
    """SVG-id-safe slug: alphanumerics + hyphen only."""
    return "".join(
        c if c.isalnum() or c in "-_" else "-" for c in name
    ) or "x"


def _humanize(ref: str) -> str:
    """Turn a slug like 'sarcophagus_grand' into 'Sarcophagus Grand'."""
    return " ".join(
        word.capitalize()
        for word in ref.replace("_", " ").replace("-", " ").split()
    ) or ref


# ----- alternate render contexts -----

class _HatchedContext(_RenderContext):
    """Render context for the hatched-style renderer.

    Hatching represents solid rock immediately OUTSIDE rooms and
    corridors — a ragged halo around the explorable space, like an
    inked dungeon map. The rest of the page stays paper-coloured.

    Implementation trick: each room/corridor outline is stroked with
    the hatch pattern at width `2 * HALO_W` (rooms) or `width + 2*HALO_W`
    (corridors). The room/corridor floor fills (drawn afterwards in
    paper colour) cover the inner half of each stroke, leaving only the
    outward-facing band of hatching visible.
    """

    # World-unit thickness of the hatched band around explorable space.
    HALO_W = 2.5

    def _bg_default(self) -> str:
        # Plain paper — hatching is drawn only as a halo, not full-bleed.
        return "#fdfaf3"

    def _floor_fill(self) -> str:
        return "#fdfaf3"

    def _corridor_floor_fill(self) -> str:
        return "#fdfaf3"

    def _extra_defs_block(self) -> str:
        # Single-direction diagonal hatch lines (Warlock-style). The
        # roughen filter perturbs the halo's outer edge so it reads as
        # hand-drawn rather than mechanically buffered.
        #
        # The tile has NO opaque backing rect — gaps between the diagonal
        # lines are transparent so whatever `map.background` is set to (or
        # the page default `_bg_default()`) shows through. That way changing
        # the map background actually recolours the negative space.
        return (
            '<defs>'
            '<pattern id="hatch" patternUnits="userSpaceOnUse" '
            'width="0.55" height="0.55" patternTransform="rotate(45)">'
            '<line x1="0" y1="0" x2="0" y2="0.55" '
            'stroke="#2b2418" stroke-width="0.11"/>'
            '</pattern>'
            '<filter id="halo-roughen" x="-5%" y="-5%" '
            'width="110%" height="110%">'
            '<feTurbulence type="fractalNoise" baseFrequency="0.45" '
            'numOctaves="2" seed="7" result="noise"/>'
            '<feDisplacementMap in="SourceGraphic" in2="noise" '
            'scale="0.55" xChannelSelector="R" yChannelSelector="G"/>'
            '</filter>'
            '</defs>'
        )

    def _pre_rooms_layer(self) -> str:
        halo_w = self.HALO_W * 2.0  # stroke is centred — half visible outside
        parts: list[str] = [
            '<g class="hatch-halo" filter="url(#halo-roughen)" '
            'fill="none" stroke="url(#hatch)" stroke-linejoin="round" '
            'stroke-linecap="round">'
        ]
        for r in self.all_rooms.values():
            d = self._room_path(r)
            if d:
                parts.append(
                    f'<path d="{d}" stroke-width="{_n(halo_w)}"/>'
                )
        all_corridors: list[Corridor] = list(self.dmap.corridors.values())
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            all_corridors.extend(layer.corridors)
        for c in all_corridors:
            cd = self._corridor_path(c)
            if not cd:
                continue
            sw = c.width + 2.0 * self.HALO_W
            parts.append(
                f'<path d="{cd}" stroke-width="{_n(sw)}"/>'
            )
        parts.append('</g>')
        return "".join(parts)
