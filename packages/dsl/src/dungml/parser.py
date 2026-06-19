"""Lark-based parser for .dmap files.

Parses the source text into a tree, then transforms the tree into the
typed semantic model defined in `dungml.model`.

The grammar lives in `grammar.lark`. We use Earley with the dynamic
lexer because the DSL has many short keywords (`at`, `to`, `from`,
`in`, ...) that overlap with the CNAME terminal; Earley + dynamic
resolves these via parser-state-aware tokenization.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from lark import Lark, Token, Transformer
from lark.exceptions import LarkError, UnexpectedInput, VisitError

from .errors import DmapParseError
from .model import (
    ArcEdge,
    ArcSegment,
    BoundaryRoom,
    CircleRoom,
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
    GridConfig,
    Label,
    Layer,
    LineEdge,
    LineFeature,
    LineSegment,
    MapConfig,
    Outline,
    Overlay,
    PolygonRoom,
    PolygonShape,
    RectRoom,
    RectShape,
    Room,
    Scenario,
    ScenarioMapRef,
    Shape,
    Slice,
    SourceSpan,
    Area,
    Marker,
    TextAnnotation,
    Window,
)

_GRAMMAR_PATH = Path(__file__).parent / "grammar.lark"

_ESCAPE_RE = re.compile(r"\\(.)")


def _unescape(s: str) -> str:
    """Apply common backslash escapes inside a regular string literal."""

    def repl(m: re.Match[str]) -> str:
        c = m.group(1)
        return {
            "n": "\n",
            "t": "\t",
            "r": "\r",
            '"': '"',
            "\\": "\\",
        }.get(c, c)

    return _ESCAPE_RE.sub(repl, s)


def _strip_string(tok: Any) -> str:
    """Return the contents of a STRING or TRIPLE_STRING token."""
    s = str(tok)
    if s.startswith('"""') and s.endswith('"""'):
        body = s[3:-3]
        # Trim a single leading and trailing newline for readability.
        if body.startswith("\n"):
            body = body[1:]
        if body.endswith("\n"):
            body = body[:-1]
        return body
    if s.startswith('"') and s.endswith('"'):
        return _unescape(s[1:-1])
    return s


def _span(tree_or_token: Any) -> SourceSpan:
    """Build a SourceSpan from a Lark Tree or Token (whichever has meta)."""
    meta = getattr(tree_or_token, "meta", None)
    if meta is None or getattr(meta, "empty", False):
        line = getattr(tree_or_token, "line", 0) or 0
        col = getattr(tree_or_token, "column", 0) or 0
        end_line = getattr(tree_or_token, "end_line", line) or line
        end_col = getattr(tree_or_token, "end_column", col) or col
        return SourceSpan(line=line, column=col, end_line=end_line, end_column=end_col)
    return SourceSpan(
        line=meta.line,
        column=meta.column,
        end_line=meta.end_line,
        end_column=meta.end_column,
    )


def _num(tok: Any) -> float:
    return float(str(tok))


def _ident(tok: Any) -> str:
    return str(tok)


def _coords_close(p: tuple[float, float], q: tuple[float, float]) -> bool:
    return abs(p[0] - q[0]) <= 1e-6 and abs(p[1] - q[1]) <= 1e-6


def _chain_run_segments(
    runs: list[tuple[str, str]],
    nodes: dict[str, tuple[float, float]],
    corridor_name: str,
) -> list[LineSegment]:
    """Resolve `run A to B` pairs into ordered LineSegments.

    Runs are greedily linked end-to-end into maximal trails (reversing a run
    where that extends a trail) so that a chain or an L-bend becomes a single
    connected sub-path at render time — preserving round wall joins at corners.
    Runs that fan out from a shared node simply start fresh trails, which the
    renderer draws as separate sub-paths meeting at the junction.
    """
    edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for a, b in runs:
        if a not in nodes:
            raise DmapParseError(
                f"corridor '{corridor_name}': run references unknown node '{a}'"
            )
        if b not in nodes:
            raise DmapParseError(
                f"corridor '{corridor_name}': run references unknown node '{b}'"
            )
        edges.append((nodes[a], nodes[b]))

    remaining = list(edges)
    out: list[LineSegment] = []
    while remaining:
        trail = [remaining.pop(0)]
        extended = True
        while extended:
            extended = False
            tail = trail[-1][1]
            for i, (c, d) in enumerate(remaining):
                if _coords_close(c, tail):
                    trail.append((c, d))
                elif _coords_close(d, tail):
                    trail.append((d, c))
                else:
                    continue
                remaining.pop(i)
                extended = True
                break
            if extended:
                continue
            head = trail[0][0]
            for i, (c, d) in enumerate(remaining):
                if _coords_close(d, head):
                    trail.insert(0, (c, d))
                elif _coords_close(c, head):
                    trail.insert(0, (d, c))
                else:
                    continue
                remaining.pop(i)
                extended = True
                break
        out.extend(LineSegment(start=s, end=e) for s, e in trail)
    return out


# ---------------------------------------------------------------------------
# Property markers
#
# Each "?_prop"-style grammar rule returns a (name, value) tuple. Parent
# blocks loop over their children and pull out the properties they care
# about by name. Sub-blocks (grid, outline, feature_block) and feature
# instances are returned as concrete model objects so they're easy to
# discriminate by isinstance.
# ---------------------------------------------------------------------------


class _Tx(Transformer):
    def __init__(self, *, require_map: bool = True) -> None:
        super().__init__()
        self.require_map = require_map
        self.includes: list[str] = []

    def include_decl(self, items: list[Any]) -> None:
        self.includes.append(_strip_string(items[0]))
        return None  # filtered out by `start`

    # ----- shared -----

    def point(self, items: list[Any]) -> tuple[float, float]:
        return (_num(items[0]), _num(items[1]))

    def ref(self, items: list[Any]) -> str:
        return ".".join(_ident(i) for i in items)

    def any_string(self, items: list[Any]) -> str:
        return _strip_string(items[0])

    # ----- map -----

    def renderer_prop(self, items: list[Any]) -> tuple[str, Any]:
        return ("renderer", _strip_string(items[0]))

    def theme_prop(self, items: list[Any]) -> tuple[str, Any]:
        return ("theme", _ident(items[0]))

    def legend_prop(self, items: list[Any]) -> tuple[str, Any]:
        return ("legend", True)

    def grid_overlay_decl(self, items: list[Any]) -> tuple[str, Any]:
        # Args are optional: `grid_overlay` alone is allowed (default
        # spacing). Filter to only Tokens — Lark may pass None placeholders
        # for absent optional terminals.
        spacing = 1.0
        color: str | None = None
        for it in items:
            if it is None:
                continue
            if isinstance(it, Token) and it.type == "NUMBER":
                spacing = _num(it)
            elif isinstance(it, Token) and it.type == "STRING":
                color = _strip_string(it)
        return ("grid_overlay", (spacing, color))

    def cell_prop(self, items: list[Any]) -> tuple[str, Any]:
        return ("cell_px", int(_num(items[0])))

    def units_prop(self, items: list[Any]) -> tuple[str, Any]:
        return ("units", (_ident(items[0]), _num(items[1])))

    def bounds_prop(self, items: list[Any]) -> tuple[str, Any]:
        return ("bounds", (_num(items[0]), _num(items[1])))

    def origin_prop(self, items: list[Any]) -> tuple[str, Any]:
        return ("origin", str(items[0]))

    def grid_block(self, items: list[Any]) -> GridConfig:
        cfg = GridConfig()
        for item in items:
            if not isinstance(item, tuple):
                continue
            key, val = item
            if key == "cell_px":
                cfg.cell_px = val
            elif key == "units":
                cfg.unit_name, cfg.unit_per_cell = val
            elif key == "bounds":
                cfg.bounds_w, cfg.bounds_h = val
            elif key == "origin":
                cfg.origin = val
        return cfg

    def party_start_decl(self, items: list[Any]) -> tuple[str, Any]:
        return ("party_start", (_num(items[0]), _num(items[1])))

    def room_numbers_decl(self, items: list[Any]) -> tuple[str, Any]:
        return ("room_numbers", str(items[0]).lower() in ("on", "true", "yes"))

    def cell_grid_decl(self, items: list[Any]) -> tuple[str, Any]:
        spacing = 1.0
        color: str | None = None
        for it in items:
            if it is None:
                continue
            if isinstance(it, Token) and it.type == "NUMBER":
                spacing = _num(it)
            elif isinstance(it, Token) and it.type == "STRING":
                color = _strip_string(it)
        return ("cell_grid", (spacing, color))

    def map_title_decl(self, items: list[Any]) -> tuple[str, Any]:
        text = _strip_string(items[0])
        pos = None
        align_v = None
        align_h = None
        size = 1.0
        rotate = 0.0
        for item in items[1:]:
            key, val = item
            if key == "pos":
                pos = val
            elif key == "align":
                align_v, align_h = val
            elif key == "size":
                size = val
            elif key == "rotate":
                rotate = val
        return (
            "title",
            Label(
                text=text, position=pos, align_v=align_v,
                align_h=align_h, size=size, rotate=rotate,
            ),
        )

    def map_block(self, items: list[Any]) -> MapConfig:
        name = _strip_string(items[0])
        grid = GridConfig()
        renderer = "classic-bw"
        theme = None
        description = None
        dm_notes = None
        legend = False
        background = None
        grid_overlay: float | None = None
        grid_overlay_color: str | None = None
        party_start = None
        room_numbers = True
        title = None
        cell_grid = None
        cell_grid_color = None
        for item in items[1:]:
            if isinstance(item, GridConfig):
                grid = item
            elif isinstance(item, tuple):
                key, val = item
                if key == "renderer":
                    renderer = val
                elif key == "theme":
                    theme = val
                elif key == "description":
                    description = val
                elif key == "dm_notes":
                    dm_notes = val
                elif key == "legend":
                    legend = val
                elif key == "background":
                    background = val
                elif key == "grid_overlay":
                    grid_overlay, grid_overlay_color = val
                elif key == "party_start":
                    party_start = val
                elif key == "room_numbers":
                    room_numbers = val
                elif key == "title":
                    title = val
                elif key == "cell_grid":
                    cell_grid, cell_grid_color = val
        return MapConfig(
            name=name,
            grid=grid,
            renderer=renderer,
            theme=theme,
            description=description,
            dm_notes=dm_notes,
            legend=legend,
            background=background,
            grid_overlay=grid_overlay,
            grid_overlay_color=grid_overlay_color,
            party_start=party_start,
            room_numbers=room_numbers,
            title=title,
            cell_grid=cell_grid,
            cell_grid_color=cell_grid_color,
        )

    # ----- scenario -----

    def scenario_map_ref(self, items: list[Any]) -> ScenarioMapRef:
        return ScenarioMapRef(path=_strip_string(items[0]))

    def scenario_block(self, items: list[Any]) -> Scenario:
        name = _strip_string(items[0])
        description = None
        dm_notes = None
        maps: list[ScenarioMapRef] = []
        for item in items[1:]:
            if isinstance(item, ScenarioMapRef):
                maps.append(item)
            elif isinstance(item, tuple):
                key, val = item
                if key == "description":
                    description = val
                elif key == "dm_notes":
                    dm_notes = val
        return Scenario(
            name=name,
            description=description,
            dm_notes=dm_notes,
            maps=maps,
        )

    # ----- shape primitives -----

    def circle_shape(self, items: list[Any]) -> CircleShape:
        return CircleShape(radius=_num(items[0]))

    def rect_shape(self, items: list[Any]) -> RectShape:
        return RectShape(width=_num(items[0]), height=_num(items[1]))

    def polygon_shape(self, items: list[Any]) -> PolygonShape:
        return PolygonShape(points=list(items))

    def shape_decl(self, items: list[Any]) -> tuple[str, Any]:
        return ("shape", items[0])

    # ----- outline -----

    def outline_color(self, items: list[Any]) -> tuple[str, Any]:
        return ("color", _strip_string(items[0]))

    def outline_width(self, items: list[Any]) -> tuple[str, Any]:
        return ("width", _num(items[0]))

    def outline_stroke(self, items: list[Any]) -> tuple[str, Any]:
        return ("stroke", _ident(items[0]))

    def outline_block(self, items: list[Any]) -> tuple[str, Any]:
        out = Outline()
        for key, val in items:
            setattr(out, key, val)
        return ("outline", out)

    # ----- overlay -----

    def overlay_offset(self, items: list[Any]) -> tuple[str, Any]:
        return ("offset", (_num(items[0]), _num(items[1])))

    def overlay_fill(self, items: list[Any]) -> tuple[str, Any]:
        return ("fill", _strip_string(items[0]))

    def overlay_decl(self, items: list[Any]) -> tuple[str, Any]:
        shape = items[0]
        offset = (0.0, 0.0)
        fill = None
        for item in items[1:]:
            key, val = item
            if key == "offset":
                offset = val
            elif key == "fill":
                fill = val
        return ("overlay", Overlay(shape=shape, offset=offset, fill=fill))

    # ----- glyph -----

    def g_stroke(self, items: list[Any]) -> str:
        return "stroke"

    def g_fill(self, items: list[Any]) -> str:
        return "fill"

    def g_plain(self, items: list[Any]) -> str:
        return "plain"

    def g_fill_color(self, items: list[Any]) -> tuple[str, Any]:
        return ("fill", _strip_string(items[0]))

    def g_stroke_color(self, items: list[Any]) -> tuple[str, Any]:
        return ("stroke", _strip_string(items[0]))

    def g_stroke_width(self, items: list[Any]) -> tuple[str, Any]:
        return ("stroke_width", _num(items[0]))

    def g_rx(self, items: list[Any]) -> tuple[str, Any]:
        return ("rx", _num(items[0]))

    def g_class(self, items: list[Any]) -> tuple[str, Any]:
        return ("extra_class", _strip_string(items[0]))

    @staticmethod
    def _glyph_styles(items: list[Any]) -> dict[str, Any]:
        return {k: v for k, v in items}

    def glyph_circle(self, items: list[Any]) -> GlyphCircle:
        role, cx, cy, r = items[0], _num(items[1]), _num(items[2]), _num(items[3])
        return GlyphCircle(role=role, cx=cx, cy=cy, r=r, **self._glyph_styles(items[4:]))

    def glyph_rect(self, items: list[Any]) -> GlyphRect:
        role = items[0]
        x, y, w, h = (_num(items[1]), _num(items[2]), _num(items[3]), _num(items[4]))
        return GlyphRect(
            role=role, x=x, y=y, width=w, height=h, **self._glyph_styles(items[5:])
        )

    def glyph_line(self, items: list[Any]) -> GlyphLine:
        role = items[0]
        x1, y1, x2, y2 = (_num(items[i]) for i in (1, 2, 3, 4))
        return GlyphLine(
            role=role, x1=x1, y1=y1, x2=x2, y2=y2, **self._glyph_styles(items[5:])
        )

    def _glyph_poly(self, items: list[Any]) -> tuple[str, list[Any], dict[str, Any]]:
        role = items[0]
        pts = [p for p in items[1:] if isinstance(p, tuple) and not isinstance(p[0], str)]
        styles = [p for p in items[1:] if isinstance(p, tuple) and isinstance(p[0], str)]
        return role, pts, self._glyph_styles(styles)

    def glyph_polygon(self, items: list[Any]) -> GlyphPolygon:
        role, pts, styles = self._glyph_poly(items)
        return GlyphPolygon(role=role, points=pts, **styles)

    def glyph_polyline(self, items: list[Any]) -> GlyphPolyline:
        role, pts, styles = self._glyph_poly(items)
        return GlyphPolyline(role=role, points=pts, **styles)

    def glyph_path(self, items: list[Any]) -> GlyphPath:
        role = items[0]
        d = _strip_string(items[1])
        return GlyphPath(role=role, d=d, **self._glyph_styles(items[2:]))

    def glyph_block(self, items: list[Any]) -> tuple[str, Any]:
        return ("glyph", list(items))

    # ----- background -----

    def background_prop(self, items: list[Any]) -> tuple[str, Any]:
        return ("background", _strip_string(items[0]))

    # ----- description -----

    def description_decl(self, items: list[Any]) -> tuple[str, Any]:
        return ("description", items[0])

    # ----- feature_def -----

    def display_name_decl(self, items: list[Any]) -> tuple[str, Any]:
        return ("display_name", _strip_string(items[0]))

    def feature_def(self, items: list[Any]) -> FeatureDef:
        name = _strip_string(items[0])
        shape: Shape | None = None
        glyph: list[Any] = []
        background = None
        outline = None
        overlays: list[Overlay] = []
        description = None
        display_name = None
        for item in items[1:]:
            if not isinstance(item, tuple):
                continue
            key, val = item
            if key == "shape":
                shape = val
            elif key == "glyph":
                glyph = val
            elif key == "background":
                background = val
            elif key == "outline":
                outline = val
            elif key == "overlay":
                overlays.append(val)
            elif key == "description":
                description = val
            elif key == "display_name":
                display_name = val
        if shape is None and not glyph:
            raise DmapParseError(
                f"feature_def '{name}' must have a `shape` or a `glyph` block"
            )
        if shape is not None and glyph:
            raise DmapParseError(
                f"feature_def '{name}' has both a `shape` and a `glyph`; "
                f"use exactly one"
            )
        return FeatureDef(
            name=name,
            shape=shape,
            glyph=glyph,
            background=background,
            outline=outline,
            overlays=overlays,
            description=description,
            display_name=display_name,
        )

    # ----- label -----

    def label_pos(self, items: list[Any]) -> tuple[str, Any]:
        return ("pos", (_num(items[0]), _num(items[1])))

    def label_size(self, items: list[Any]) -> tuple[str, Any]:
        return ("size", _num(items[0]))

    def label_rotate(self, items: list[Any]) -> tuple[str, Any]:
        return ("rotate", _num(items[0]))

    def label_align(self, items: list[Any]) -> tuple[str, Any]:
        # Grammar enforces vertical-then-horizontal order.
        return ("align", (str(items[0]), str(items[1])))

    def label_decl(self, items: list[Any]) -> tuple[str, Any]:
        text = _strip_string(items[0])
        pos = None
        align_v = None
        align_h = None
        size = 1.0
        rotate = 0.0
        for item in items[1:]:
            key, val = item
            if key == "pos":
                pos = val
            elif key == "align":
                align_v, align_h = val
            elif key == "size":
                size = val
            elif key == "rotate":
                rotate = val
        return (
            "label",
            Label(
                text=text,
                position=pos,
                align_v=align_v,
                align_h=align_h,
                size=size,
                rotate=rotate,
            ),
        )

    # ----- feature instance -----

    def feature_ref(self, items: list[Any]) -> str:
        tok = items[0]
        if isinstance(tok, Token) and tok.type == "STRING":
            return _strip_string(tok)
        return _ident(tok)

    def feat_rotate(self, items: list[Any]) -> tuple[str, Any]:
        return ("rotate", _num(items[0]))

    def feat_scale(self, items: list[Any]) -> tuple[str, Any]:
        sx = _num(items[0])
        # `scale 2:1` → (2, 1); `scale 2` → (2, None) meaning uniform.
        sy = _num(items[1]) if len(items) > 1 else None
        return ("scale", (sx, sy))

    def feature_block(self, items: list[Any]) -> tuple[str, Any]:
        # description_decl and dm_notes_decl tuples appear inside.
        description = None
        dm_notes = None
        for item in items:
            if not isinstance(item, tuple):
                continue
            if item[0] == "description":
                description = item[1]
            elif item[0] == "dm_notes":
                dm_notes = item[1]
        return ("inline_block", {"description": description, "dm_notes": dm_notes})

    def feature_inst(self, items: list[Any]) -> FeatureInstance:
        # items: [ref, x, y, *modifiers, optional inline_block tuple]
        ref = items[0]
        x = _num(items[1])
        y = _num(items[2])
        rotate = 0.0
        scale = 1.0
        scale_y = None
        description = None
        dm_notes = None
        for item in items[3:]:
            if not isinstance(item, tuple):
                continue
            key, val = item
            if key == "rotate":
                rotate = val
            elif key == "scale":
                scale, scale_y = val
            elif key == "inline_block":
                description = val.get("description")
                dm_notes = val.get("dm_notes")
        return FeatureInstance(
            ref=ref,
            position=(x, y),
            rotate=rotate,
            scale=scale,
            scale_y=scale_y,
            description=description,
            dm_notes=dm_notes,
        )

    # ----- room -----

    def rect_room(self, items: list[Any]) -> RectRoom:
        return RectRoom(
            position=(_num(items[0]), _num(items[1])),
            width=_num(items[2]),
            height=_num(items[3]),
        )

    def polygon_room(self, items: list[Any]) -> PolygonRoom:
        return PolygonRoom(points=list(items))

    def circle_room(self, items: list[Any]) -> CircleRoom:
        return CircleRoom(
            center=(_num(items[0]), _num(items[1])),
            radius=_num(items[2]),
        )

    def boundary_start(self, items: list[Any]) -> tuple[str, Any]:
        return ("start", (_num(items[0]), _num(items[1])))

    def boundary_line(self, items: list[Any]) -> LineEdge:
        return LineEdge(end=(_num(items[0]), _num(items[1])))

    def boundary_arc(self, items: list[Any]) -> ArcEdge:
        return ArcEdge(
            end=(_num(items[0]), _num(items[1])),
            via=(_num(items[2]), _num(items[3])),
        )

    def boundary_room(self, items: list[Any]) -> BoundaryRoom:
        start: tuple[float, float] | None = None
        edges: list[Any] = []
        for item in items:
            if isinstance(item, tuple) and item[0] == "start":
                start = item[1]
            elif isinstance(item, (LineEdge, ArcEdge)):
                edges.append(item)
        if start is None:
            raise DmapParseError("boundary { ... } is missing a `start` point")
        return BoundaryRoom(start=start, edges=edges)

    def room_grid(self, items: list[Any]) -> tuple[str, Any]:
        spacing = _num(items[0])
        color = _strip_string(items[1]) if len(items) > 1 else None
        return ("grid", (spacing, color))

    def dm_notes_decl(self, items: list[Any]) -> tuple[str, Any]:
        return ("dm_notes", items[0])

    def line_style_decl(self, items: list[Any]) -> tuple[str, Any]:
        amount = _num(items[1]) if len(items) > 1 else None
        return ("line_style", (_ident(items[0]), amount))

    def allow_overlap_decl(self, items: list[Any]) -> tuple[str, Any]:
        return ("allow_overlap", True)

    def room(self, items: list[Any]) -> Room:
        name = _strip_string(items[0])
        shape: RectRoom | PolygonRoom | BoundaryRoom | CircleRoom | None = None
        label = None
        description = None
        dm_notes = None
        features: list[FeatureInstance] = []
        grid: float | None = None
        grid_color: str | None = None
        background = None
        line_style = None
        line_style_amount = None
        allow_overlap = False
        for item in items[1:]:
            if isinstance(item, (RectRoom, PolygonRoom, BoundaryRoom, CircleRoom)):
                shape = item
            elif isinstance(item, FeatureInstance):
                features.append(item)
            elif isinstance(item, tuple):
                key, val = item
                if key == "label":
                    label = val
                elif key == "description":
                    description = val
                elif key == "dm_notes":
                    dm_notes = val
                elif key == "grid":
                    grid, grid_color = val
                elif key == "background":
                    background = val
                elif key == "line_style":
                    line_style, line_style_amount = val
                elif key == "allow_overlap":
                    allow_overlap = val
        if shape is None:
            raise DmapParseError(f"room '{name}' is missing a shape (rect, polygon, or boundary)")
        return Room(
            name=name,
            shape=shape,
            label=label,
            description=description,
            dm_notes=dm_notes,
            features=features,
            grid=grid,
            grid_color=grid_color,
            background=background,
            line_style=line_style,
            line_style_amount=line_style_amount,
            allow_overlap=allow_overlap,
        )

    # ----- corridor -----

    def corridor_width(self, items: list[Any]) -> tuple[str, Any]:
        return ("width", _num(items[0]))

    def line_segment(self, items: list[Any]) -> LineSegment:
        return LineSegment(
            start=(_num(items[0]), _num(items[1])),
            end=(_num(items[2]), _num(items[3])),
        )

    def sweep_modifier(self, items: list[Any]) -> tuple[str, Any]:
        return ("sweep", str(items[0]))

    def arc_segment(self, items: list[Any]) -> ArcSegment:
        sweep = "ccw"
        for item in items[5:]:
            if isinstance(item, tuple) and item[0] == "sweep":
                sweep = item[1]
        return ArcSegment(
            center=(_num(items[0]), _num(items[1])),
            radius=_num(items[2]),
            from_angle=_num(items[3]),
            to_angle=_num(items[4]),
            sweep=sweep,
        )

    def segment_decl(self, items: list[Any]) -> Any:
        return items[0]

    def corridor_node(self, items: list[Any]) -> tuple[str, Any]:
        return ("node", (str(items[0]), (_num(items[1]), _num(items[2]))))

    def corridor_run(self, items: list[Any]) -> tuple[str, Any]:
        return ("run", (str(items[0]), str(items[1])))

    def corridor_corners(self, items: list[Any]) -> tuple[str, Any]:
        return ("corners", _ident(items[0]))

    def corridor(self, items: list[Any]) -> Corridor:
        name = _strip_string(items[0])
        # Optional second STRING (display name) follows the slug.
        rest_start = 1
        display_name: str | None = None
        if len(items) > 1 and isinstance(items[1], Token) and items[1].type in (
            "STRING",
            "TRIPLE_STRING",
        ):
            display_name = _strip_string(items[1])
            rest_start = 2
        width = 1.0
        segments: list[Any] = []
        nodes: dict[str, Any] = {}
        runs: list[tuple[str, str]] = []
        label = None
        description = None
        dm_notes = None
        background = None
        line_style = None
        line_style_amount = None
        corners = "round"
        for item in items[rest_start:]:
            if isinstance(item, (LineSegment, ArcSegment)):
                segments.append(item)
            elif isinstance(item, tuple):
                key, val = item
                if key == "width":
                    width = val
                elif key == "node":
                    nodes[val[0]] = val[1]
                elif key == "run":
                    runs.append(val)
                elif key == "corners":
                    corners = val
                elif key == "label":
                    label = val
                elif key == "description":
                    description = val
                elif key == "dm_notes":
                    dm_notes = val
                elif key == "background":
                    background = val
                elif key == "line_style":
                    line_style, line_style_amount = val
        # Desugar `run`s into line segments, appended after any explicit
        # `segment`s. Named junctions are kept on the model for tooling.
        segments.extend(_chain_run_segments(runs, nodes, name))
        return Corridor(
            name=name,
            display_name=display_name,
            width=width,
            segments=segments,
            nodes=nodes,
            label=label,
            description=description,
            dm_notes=dm_notes,
            background=background,
            line_style=line_style,
            line_style_amount=line_style_amount,
            corners=corners,
        )

    # ----- slice -----

    def slice_kind(self, items: list[Any]) -> tuple[str, Any]:
        return ("kind", str(items[0]))

    def slice_width(self, items: list[Any]) -> tuple[str, Any]:
        return ("width", _num(items[0]))

    def slice_decl(self, items: list[Any]) -> Slice:
        name = _strip_string(items[0])
        kind: str = "river"
        width = 2.0
        segments: list[Any] = []
        label = None
        description = None
        dm_notes = None
        for item in items[1:]:
            if isinstance(item, (LineSegment, ArcSegment)):
                segments.append(item)
                continue
            if not isinstance(item, tuple):
                continue
            key, val = item
            if key == "kind":
                kind = val
            elif key == "width":
                width = val
            elif key == "label":
                label = val
            elif key == "description":
                description = val
            elif key == "dm_notes":
                dm_notes = val
        return Slice(
            name=name,
            kind=kind,  # type: ignore[arg-type]
            width=width,
            segments=segments,
            label=label,
            description=description,
            dm_notes=dm_notes,
        )

    # ----- door -----

    def door_connects(self, items: list[Any]) -> tuple[str, Any]:
        return ("connects", [str(r) for r in items])

    def door_type(self, items: list[Any]) -> tuple[str, Any]:
        return ("type", _ident(items[0]))

    def door_state(self, items: list[Any]) -> tuple[str, Any]:
        return ("state", _ident(items[0]))

    def door_facing(self, items: list[Any]) -> tuple[str, Any]:
        return ("facing", _ident(items[0]))

    def door_width(self, items: list[Any]) -> tuple[str, Any]:
        return ("width", _num(items[0]))

    def door(self, items: list[Any]) -> Door:
        x = _num(items[0])
        y = _num(items[1])
        connects: list[str] = []
        dtype = "wooden"
        state = "closed"
        facing = None
        width = 1.0
        description = None
        dm_notes = None
        for item in items[2:]:
            if not isinstance(item, tuple):
                continue
            key, val = item
            if key == "connects":
                connects = val
            elif key == "type":
                dtype = val
            elif key == "state":
                state = val
            elif key == "facing":
                facing = val
            elif key == "width":
                width = val
            elif key == "description":
                description = val
            elif key == "dm_notes":
                dm_notes = val
        return Door(
            position=(x, y),
            connects=connects,
            type=dtype,
            state=state,
            facing=facing,
            width=width,
            description=description,
            dm_notes=dm_notes,
        )

    # ----- window -----

    def window_in(self, items: list[Any]) -> tuple[str, Any]:
        return ("in", str(items[0]))

    def window_width(self, items: list[Any]) -> tuple[str, Any]:
        return ("width", _num(items[0]))

    def window(self, items: list[Any]) -> Window:
        x = _num(items[0])
        y = _num(items[1])
        in_ref = ""
        width = 1.0
        description = None
        for item in items[2:]:
            if not isinstance(item, tuple):
                continue
            key, val = item
            if key == "in":
                in_ref = val
            elif key == "width":
                width = val
            elif key == "description":
                description = val
        return Window(position=(x, y), in_ref=in_ref, width=width, description=description)

    # ----- marker -----

    def marker_tag(self, items: list[Any]) -> tuple[str, Any]:
        item = items[0]
        # CNAME → palette key; STRING → CSS colour literal (verbatim).
        if isinstance(item, Token) and item.type == "STRING":
            return ("tag", _strip_string(item))
        return ("tag", str(item))

    def marker_label(self, items: list[Any]) -> tuple[str, Any]:
        return ("label", _strip_string(items[0]))

    def marker_initial(self, items: list[Any]) -> tuple[str, Any]:
        return ("initial", _strip_string(items[0]))

    def marker_size(self, items: list[Any]) -> tuple[str, Any]:
        return ("size", _num(items[0]))

    def marker_location(self, items: list[Any]) -> tuple[str, Any]:
        return ("location", str(items[0]))

    def marker_image(self, items: list[Any]) -> tuple[str, Any]:
        return ("image", _strip_string(items[0]))

    def marker(self, items: list[Any]) -> Marker:
        name = _strip_string(items[0])
        x = _num(items[1])
        y = _num(items[2])
        kwargs: dict[str, Any] = {}
        for item in items[3:]:
            if not isinstance(item, tuple):
                continue
            key, val = item
            kwargs[key] = val
        return Marker(name=name, position=(x, y), **kwargs)

    # ----- text annotation -----

    def text_size(self, items: list[Any]) -> tuple[str, Any]:
        return ("size", _num(items[0]))

    def text_rotate(self, items: list[Any]) -> tuple[str, Any]:
        return ("rotate", _num(items[0]))

    def text_annotation(self, items: list[Any]) -> TextAnnotation:
        text = _strip_string(items[0])
        x = _num(items[1])
        y = _num(items[2])
        # Remaining items are (key, value) tuples whose keys all match
        # TextAnnotation fields (size, rotate, description, dm_notes).
        kwargs: dict[str, Any] = {}
        for item in items[3:]:
            if not isinstance(item, tuple):
                continue
            key, val = item
            kwargs[key] = val
        return TextAnnotation(text=text, position=(x, y), **kwargs)

    # ----- area -----

    def area_kind(self, items: list[Any]) -> tuple[str, Any]:
        return ("kind", _ident(items[0]))

    def area(self, items: list[Any]) -> Area:
        name = _strip_string(items[0])
        shape: RectRoom | PolygonRoom | BoundaryRoom | CircleRoom | None = None
        kind = "water"
        label = None
        background = None
        line_style = None
        line_style_amount = None
        description = None
        dm_notes = None
        for item in items[1:]:
            if isinstance(item, (RectRoom, PolygonRoom, BoundaryRoom, CircleRoom)):
                shape = item
            elif isinstance(item, tuple):
                key, val = item
                if key == "kind":
                    kind = val
                elif key == "label":
                    label = val
                elif key == "background":
                    background = val
                elif key == "line_style":
                    line_style, line_style_amount = val
                elif key == "description":
                    description = val
                elif key == "dm_notes":
                    dm_notes = val
        if shape is None:
            raise DmapParseError(f"area '{name}' has no shape")
        return Area(
            name=name,
            kind=kind,
            shape=shape,
            label=label,
            background=background,
            line_style=line_style,
            line_style_amount=line_style_amount,
            description=description,
            dm_notes=dm_notes,
        )

    # ----- line feature -----

    def lf_kind(self, items: list[Any]) -> tuple[str, Any]:
        return ("kind", _ident(items[0]))

    def lf_point(self, items: list[Any]) -> tuple[str, Any]:
        return ("point", (_num(items[0]), _num(items[1])))

    def line_feature(self, items: list[Any]) -> LineFeature:
        name = _strip_string(items[0])
        kind = "bars"
        points: list[tuple[float, float]] = []
        description = None
        dm_notes = None
        for item in items[1:]:
            if not isinstance(item, tuple):
                continue
            key, val = item
            if key == "kind":
                kind = val
            elif key == "point":
                points.append(val)
            elif key == "description":
                description = val
            elif key == "dm_notes":
                dm_notes = val
        return LineFeature(
            name=name, kind=kind, points=points,
            description=description, dm_notes=dm_notes,
        )

    # ----- layer -----

    def hidden_flag(self, items: list[Any]) -> tuple[str, Any]:
        return ("hidden", True)

    def layer(self, items: list[Any]) -> Layer:
        name = _strip_string(items[0])
        hidden = False
        rooms: list[Room] = []
        corridors: list[Corridor] = []
        slices: list[Slice] = []
        features: list[FeatureInstance] = []
        doors: list[Door] = []
        windows: list[Window] = []
        markers: list[Marker] = []
        texts: list[TextAnnotation] = []
        areas: list[Area] = []
        line_features: list[LineFeature] = []
        for item in items[1:]:
            if isinstance(item, tuple) and item[0] == "hidden":
                hidden = item[1]
            elif isinstance(item, Room):
                rooms.append(item)
            elif isinstance(item, Corridor):
                corridors.append(item)
            elif isinstance(item, Slice):
                slices.append(item)
            elif isinstance(item, FeatureInstance):
                features.append(item)
            elif isinstance(item, Door):
                doors.append(item)
            elif isinstance(item, Window):
                windows.append(item)
            elif isinstance(item, Marker):
                markers.append(item)
            elif isinstance(item, TextAnnotation):
                texts.append(item)
            elif isinstance(item, Area):
                areas.append(item)
            elif isinstance(item, LineFeature):
                line_features.append(item)
        return Layer(
            name=name,
            hidden=hidden,
            rooms=rooms,
            corridors=corridors,
            slices=slices,
            features=features,
            doors=doors,
            windows=windows,
            markers=markers,
            texts=texts,
            areas=areas,
            line_features=line_features,
        )

    # ----- start -----

    def start(self, items: list[Any]) -> DungeonMap:
        map_cfg: MapConfig | None = None
        scenario_cfg: Scenario | None = None
        feature_defs: dict[str, FeatureDef] = {}
        rooms: dict[str, Room] = {}
        corridors: dict[str, Corridor] = {}
        slices: dict[str, Slice] = {}
        features: list[FeatureInstance] = []
        doors: list[Door] = []
        windows: list[Window] = []
        markers: list[Marker] = []
        texts: list[TextAnnotation] = []
        areas: list[Area] = []
        line_features: list[LineFeature] = []
        layers: list[Layer] = []
        for item in items:
            if isinstance(item, MapConfig):
                map_cfg = item
            elif isinstance(item, Scenario):
                if scenario_cfg is not None:
                    raise DmapParseError(
                        "file has more than one `scenario { ... }` block"
                    )
                scenario_cfg = item
            elif isinstance(item, FeatureDef):
                feature_defs[item.name] = item
            elif isinstance(item, Room):
                rooms[item.name] = item
            elif isinstance(item, Corridor):
                corridors[item.name] = item
            elif isinstance(item, Slice):
                slices[item.name] = item
            elif isinstance(item, FeatureInstance):
                features.append(item)
            elif isinstance(item, Door):
                doors.append(item)
            elif isinstance(item, Window):
                windows.append(item)
            elif isinstance(item, Marker):
                markers.append(item)
            elif isinstance(item, TextAnnotation):
                texts.append(item)
            elif isinstance(item, Area):
                areas.append(item)
            elif isinstance(item, LineFeature):
                line_features.append(item)
            elif isinstance(item, Layer):
                layers.append(item)
        if map_cfg is not None and scenario_cfg is not None:
            raise DmapParseError(
                "file has both a top-level `map` and a `scenario` — pick one"
            )
        if map_cfg is None and scenario_cfg is None and self.require_map:
            raise DmapParseError(
                "file is missing a top-level `map { ... }` "
                "or `scenario { ... }` block"
            )
        if map_cfg is not None and not self.require_map:
            raise DmapParseError(
                "included files must not contain a `map { ... }` block"
            )
        return DungeonMap(
            map=map_cfg or MapConfig(name="<scenario>" if scenario_cfg else "<included>"),
            feature_defs=feature_defs,
            rooms=rooms,
            corridors=corridors,
            slices=slices,
            features=features,
            doors=doors,
            windows=windows,
            markers=markers,
            texts=texts,
            areas=areas,
            line_features=line_features,
            layers=layers,
            scenario=scenario_cfg,
        )


# ---------------------------------------------------------------------------
# Span attachment
#
# Lark's tree-level meta (line/column) gives us spans for free, but the
# Transformer above replaces each Tree node with its concrete model
# object before we can read it. To recover spans we run a second pass:
# parse → tree, then post-process per top-level node, attaching its
# original meta onto the corresponding model instance.
# ---------------------------------------------------------------------------


def _attach_spans(tree: Any, model: DungeonMap) -> None:
    """Best-effort: walk the parse tree and tag spans onto matching model
    objects. We match top-level objects by their identifier (name or
    position) since the source text is what we ultimately care about
    for editor diagnostics.
    """
    from lark import Tree

    def walk(node: Tree) -> None:
        if not hasattr(node, "data"):
            return

        if node.data == "map_block" and getattr(node, "meta", None):
            model.map.span = _span(node)

        elif node.data == "feature_def":
            name = _strip_string(node.children[0])
            if name in model.feature_defs:
                model.feature_defs[name].span = _span(node)

        elif node.data == "room":
            name = _strip_string(node.children[0])
            if name in model.rooms:
                model.rooms[name].span = _span(node)

        elif node.data == "corridor":
            name = _strip_string(node.children[0])
            if name in model.corridors:
                model.corridors[name].span = _span(node)

        elif node.data == "door":
            x, y = float(str(node.children[0])), float(str(node.children[1]))
            for d in model.doors:
                if d.position == (x, y) and d.span.line == 0:
                    d.span = _span(node)
                    break

        elif node.data == "window":
            x, y = float(str(node.children[0])), float(str(node.children[1]))
            for w in model.windows:
                if w.position == (x, y) and w.span.line == 0:
                    w.span = _span(node)
                    break

        elif node.data == "text_annotation":
            text = _strip_string(node.children[0])
            x, y = float(str(node.children[1])), float(str(node.children[2]))
            for t in model.texts:
                if (
                    t.text == text
                    and t.position == (x, y)
                    and t.span.line == 0
                ):
                    t.span = _span(node)
                    break

        elif node.data == "area":
            name = _strip_string(node.children[0])
            for a in model.areas:
                if a.name == name and a.span.line == 0:
                    a.span = _span(node)
                    break

        elif node.data == "layer":
            name = _strip_string(node.children[0])
            for layer in model.layers:
                if layer.name == name and layer.span.line == 0:
                    layer.span = _span(node)
                    break

        for child in node.children:
            if isinstance(child, Tree):
                walk(child)

    walk(tree)


_parser: Lark | None = None

_LIBRARY_DIR = Path(__file__).parent / "includes"


def _get_parser() -> Lark:
    global _parser
    if _parser is None:
        _parser = Lark.open(
            str(_GRAMMAR_PATH),
            parser="earley",
            lexer="dynamic_complete",
            propagate_positions=True,
            maybe_placeholders=False,
        )
    return _parser


def list_libraries() -> list[str]:
    """Sorted names of the bundled include libraries (e.g. ``"core.dmap"``,
    ``"forest.dmap"``). These can be `include`d directly or copied into a
    project as editable library maps."""
    try:
        return sorted(p.name for p in _LIBRARY_DIR.glob("*.dmap"))
    except OSError:
        return []


def library_source(name: str) -> str | None:
    """Return the text of a bundled include library (e.g. ``"core.dmap"``).

    Used to snapshot a built-in library into a project that then owns an
    editable copy. Returns None if no such bundled library exists.
    """
    p = _LIBRARY_DIR / name
    try:
        if p.is_file():
            return p.read_text(encoding="utf-8")
    except OSError:
        return None
    return None


def _resolve_include(name: str, base_dir: Path | None) -> Path | None:
    """Find an include by name. Search order:

    1. Relative to `base_dir` (the including file's directory).
    2. The bundled `includes/` library shipped with dungml.
    3. As an absolute / cwd-relative path.
    """
    candidates: list[Path] = []
    if base_dir is not None:
        candidates.append((base_dir / name))
    candidates.append((_LIBRARY_DIR / name))
    candidates.append(Path(name))
    for c in candidates:
        try:
            resolved = c.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _merge(into: DungeonMap, other: DungeonMap) -> None:
    """Splice the included model's entities into `into`.

    The main file wins on naming collisions (setdefault), so includes
    can ship sensible defaults that users override locally.
    """
    for name, fd in other.feature_defs.items():
        into.feature_defs.setdefault(name, fd)
    for name, r in other.rooms.items():
        into.rooms.setdefault(name, r)
    for name, c in other.corridors.items():
        into.corridors.setdefault(name, c)
    for name, s in other.slices.items():
        into.slices.setdefault(name, s)
    into.features.extend(other.features)
    into.doors.extend(other.doors)
    into.windows.extend(other.windows)
    into.layers.extend(other.layers)


def _parse_text(
    text: str,
    *,
    require_map: bool,
) -> tuple[DungeonMap, list[str]]:
    """Parse one source string. Returns the model and any include paths."""
    try:
        tree = _get_parser().parse(text)
    except UnexpectedInput as e:
        raise DmapParseError(
            f"unexpected input: {e.__class__.__name__}",
            line=getattr(e, "line", 0) or 0,
            column=getattr(e, "column", 0) or 0,
        ) from e
    except LarkError as e:
        raise DmapParseError(str(e)) from e
    tx = _Tx(require_map=require_map)
    try:
        model = tx.transform(tree)
    except VisitError as e:
        if isinstance(e.orig_exc, DmapParseError):
            raise e.orig_exc from None
        raise DmapParseError(str(e.orig_exc)) from e
    _attach_spans(tree, model)
    return model, tx.includes


def parse(
    text: str,
    *,
    path: str | Path | None = None,
    include_sources: Mapping[str, str] | None = None,
) -> DungeonMap:
    """Parse a .dmap source string into a typed DungeonMap.

    If `path` is given, it's used as the source file's location so
    `include` directives can resolve relative paths. Without it,
    includes only resolve against the bundled library.

    `include_sources` maps an include name (e.g. `"core.dmap"`) to its
    source text. When present, an `include` is satisfied from this map
    *before* any filesystem lookup — this is how the backend resolves
    `include "core.dmap"` to a project's own editable copy rather than
    the bundled library. Names not present fall back to the filesystem.

    The built-in feature library lives in the bundled `core.dmap`; bring
    it in explicitly with `include "core.dmap"` to use features like
    `pillar`, `stairs-up`, `bridge`, etc.

    Raises DmapParseError on any grammar-level failure or cycle.
    """
    base_dir = Path(path).resolve().parent if path else None
    seen: set[str] = set()
    if path:
        try:
            seen.add(str(Path(path).resolve()))
        except OSError:
            pass
    model, includes = _parse_text(text, require_map=True)
    for inc_name in includes:
        _load_include_into(model, inc_name, base_dir, seen, include_sources)
    return model


def parse_scenario(text: str, *, path: str | Path | None = None) -> Scenario:
    """Parse a .dmap source string whose top-level block is a `scenario`.

    Same include resolution and error conventions as `parse()`. Raises
    DmapParseError if the file does not contain a `scenario { ... }`
    block. Scenarios are otherwise stripped of any non-scenario state.
    """
    model = parse(text, path=path)
    if model.scenario is None:
        raise DmapParseError(
            "file does not contain a `scenario { ... }` block; "
            "use parse() for ordinary map files"
        )
    return model.scenario


def _load_include_into(
    model: DungeonMap,
    inc_name: str,
    base_dir: Path | None,
    seen: set[str],
    include_sources: Mapping[str, str] | None = None,
    origins: dict[str, str] | None = None,
) -> None:
    # `origins` (optional) records which file first defined each feature_def
    # — `setdefault` keeps the active (first-wins) provider for provenance.
    # In-memory sources (e.g. a project's own maps) win over the
    # filesystem so an edited `core.dmap` takes precedence over the
    # bundled copy.
    if include_sources is not None and inc_name in include_sources:
        key = f"src::{inc_name}"
        if key in seen:
            return  # cycle — silently skip
        seen.add(key)
        included, nested_includes = _parse_text(
            include_sources[inc_name], require_map=False
        )
        if origins is not None:
            for fname in included.feature_defs:
                origins.setdefault(fname, inc_name)
        _merge(model, included)
        for nested in nested_includes:
            _load_include_into(
                model, nested, None, seen, include_sources, origins
            )
        return

    resolved = _resolve_include(inc_name, base_dir)
    if resolved is None:
        raise DmapParseError(f'include not found: "{inc_name}"')
    key = str(resolved)
    if key in seen:
        return  # cycle — silently skip
    seen.add(key)
    included_text = resolved.read_text(encoding="utf-8")
    included, nested_includes = _parse_text(included_text, require_map=False)
    if origins is not None:
        for fname in included.feature_defs:
            origins.setdefault(fname, inc_name)
    _merge(model, included)
    for nested in nested_includes:
        _load_include_into(
            model, nested, resolved.parent, seen, include_sources, origins
        )


# Label used for feature_defs defined directly in the map (not an include).
LOCAL_ORIGIN = "(this file)"


def feature_def_origins(
    text: str,
    *,
    path: str | Path | None = None,
    include_sources: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Map each available feature_def name to the file that defines it.

    Same include resolution as `parse()`. Names defined directly in `text`
    map to `LOCAL_ORIGIN`; names from an include map to that include's name
    (e.g. ``"core.dmap"``). First definition wins, matching render
    precedence. Returns an empty dict on parse failure.
    """
    base_dir = Path(path).resolve().parent if path else None
    seen: set[str] = set()
    if path:
        try:
            seen.add(str(Path(path).resolve()))
        except OSError:
            pass
    # The source may be a map (has a `map { }` block) or a library file
    # (must not) — try map-mode first, fall back to include-mode.
    model = None
    includes: list[str] = []
    for require_map in (True, False):
        try:
            model, includes = _parse_text(text, require_map=require_map)
            break
        except DmapParseError:
            continue
    if model is None:
        return {}
    origins: dict[str, str] = {
        name: LOCAL_ORIGIN for name in model.feature_defs
    }
    for inc_name in includes:
        _load_include_into(
            model, inc_name, base_dir, seen, include_sources, origins
        )
    return origins
