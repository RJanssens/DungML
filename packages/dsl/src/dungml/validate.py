"""Semantic validation pass over a parsed DungeonMap.

Catches what the grammar cannot: dangling references, duplicate names,
polygons with too few points, doors connecting to non-existent rooms,
window/door positions outside the map bounds, etc.

Validation is *additive* — it returns a list of Diagnostics. Callers
decide whether to treat warnings as fatal.
"""
from __future__ import annotations

from .builtins import BUILTIN_FEATURES
from .errors import Diagnostic
from .geometry import Area, corridor_polygons, find_overlapping_areas, room_polygon

# Minimum interior-overlap area (square map units) before an overlap is
# worth reporting. Below this, an overlap is a cosmetic sliver — typically
# a corridor poking into the room it connects, or two corridors meeting at
# a bend — which is normal authoring, not a mistake.
OVERLAP_MIN_AREA = 1.0

# Built-in `area` kinds (kept loosely in sync with the renderer's palette).
# Unknown kinds still render (neutral fallback) but earn a warning.
KNOWN_AREA_KINDS = {
    "water", "lava", "pit", "chasm", "mud", "acid", "ice", "blood",
    "slime", "swamp",
}
KNOWN_LINE_FEATURE_KINDS = {"bars", "curtain", "barred"}
from .model import (
    BoundaryRoom,
    CircleRoom,
    Corridor,
    DungeonMap,
    FeatureInstance,
    GlyphPolygon,
    GlyphPolyline,
    PolygonRoom,
    PolygonShape,
    RectRoom,
    Room,
    SourceSpan,
)


def _diag(severity: str, message: str, span: SourceSpan | None = None) -> Diagnostic:
    s = span or SourceSpan()
    return Diagnostic(
        severity=severity,
        message=message,
        line=s.line,
        column=s.column,
        end_line=s.end_line,
        end_column=s.end_column,
    )


def _in_bounds(pos: tuple[float, float], w: float, h: float) -> bool:
    x, y = pos
    return 0 <= x <= w and 0 <= y <= h


def validate(dmap: DungeonMap) -> list[Diagnostic]:
    """Return all diagnostics found in `dmap`. Empty list = valid."""
    diags: list[Diagnostic] = []
    bw = dmap.map.grid.bounds_w
    bh = dmap.map.grid.bounds_h

    known_features = set(dmap.feature_defs.keys())
    known_rooms = set(dmap.rooms.keys())
    known_corridors = set(dmap.corridors.keys())

    def check_feature_inst(fi: FeatureInstance, *, scope: str) -> None:
        if fi.ref not in known_features:
            hint = ""
            if fi.ref in BUILTIN_FEATURES:
                hint = ' — add `include "core.dmap"` for the built-in library'
            diags.append(
                _diag(
                    "error",
                    f"unknown feature '{fi.ref}' in {scope}: "
                    f"no matching feature_def{hint}",
                    fi.span,
                )
            )
        if not _in_bounds(fi.position, bw, bh):
            diags.append(
                _diag(
                    "warning",
                    f"feature '{fi.ref}' at {fi.position} is outside the map bounds "
                    f"({bw} x {bh})",
                    fi.span,
                )
            )
        if fi.scale <= 0 or (fi.scale_y is not None and fi.scale_y <= 0):
            shown = fi.scale if fi.scale_y is None else f"{fi.scale}:{fi.scale_y}"
            diags.append(
                _diag("error", f"feature scale must be positive (got {shown})", fi.span)
            )

    # ---- feature_def shape / glyph arity ----
    for fd in dmap.feature_defs.values():
        if isinstance(fd.shape, PolygonShape) and len(fd.shape.points) < 3:
            diags.append(
                _diag(
                    "error",
                    f"feature_def '{fd.name}' polygon has only {len(fd.shape.points)} "
                    f"point(s); need at least 3",
                    fd.span,
                )
            )
        for g in fd.glyph:
            need = 3 if isinstance(g, GlyphPolygon) else 2
            if isinstance(g, (GlyphPolygon, GlyphPolyline)) and len(g.points) < need:
                diags.append(
                    _diag(
                        "error",
                        f"feature_def '{fd.name}' glyph {g.kind} has only "
                        f"{len(g.points)} point(s); need at least {need}",
                        fd.span,
                    )
                )

    # ---- rooms ----
    for name, room in dmap.rooms.items():
        if isinstance(room.shape, RectRoom):
            if room.shape.width <= 0 or room.shape.height <= 0:
                diags.append(
                    _diag(
                        "error",
                        f"room '{name}' has non-positive dimensions "
                        f"({room.shape.width} x {room.shape.height})",
                        room.span,
                    )
                )
        elif isinstance(room.shape, PolygonRoom):
            if len(room.shape.points) < 3:
                diags.append(
                    _diag(
                        "error",
                        f"room '{name}' polygon has only {len(room.shape.points)} "
                        f"point(s); need at least 3",
                        room.span,
                    )
                )
        elif isinstance(room.shape, BoundaryRoom):
            if len(room.shape.edges) < 2:
                diags.append(
                    _diag(
                        "error",
                        f"room '{name}' boundary has only {len(room.shape.edges)} "
                        f"edge(s); need at least 2",
                        room.span,
                    )
                )
        elif isinstance(room.shape, CircleRoom):
            if room.shape.radius <= 0:
                diags.append(
                    _diag(
                        "error",
                        f"room '{name}' has non-positive radius "
                        f"({room.shape.radius})",
                        room.span,
                    )
                )

        # Label position (if explicit) should sit inside the map bounds.
        if room.label and room.label.position is not None:
            if not _in_bounds(room.label.position, bw, bh):
                diags.append(
                    _diag(
                        "warning",
                        f"room '{name}' label position {room.label.position} is outside "
                        f"the map bounds",
                        room.span,
                    )
                )

        for fi in room.features:
            check_feature_inst(fi, scope=f"room '{name}'")

    # ---- top-level (map-wide) features ----
    for fi in dmap.features:
        check_feature_inst(fi, scope="map")

    # ---- corridors ----
    for name, corr in dmap.corridors.items():
        # width 0 is allowed — it renders as a single centerline (a route /
        # passage line). Only a negative width is an error.
        if corr.width < 0:
            diags.append(
                _diag(
                    "error",
                    f"corridor '{name}' has negative width ({corr.width})",
                    corr.span,
                )
            )
        if not corr.segments:
            diags.append(
                _diag("warning", f"corridor '{name}' has no segments", corr.span)
            )

    # ---- doors ----
    for door in dmap.doors:
        if not door.connects:
            diags.append(
                _diag(
                    "warning",
                    f"door at {door.position} has no `connects` references; "
                    f"its semantic role is undefined",
                    door.span,
                )
            )
        for ref in door.connects:
            kind, _, ident = ref.partition(".")
            if kind == "room":
                if ident not in known_rooms:
                    diags.append(
                        _diag(
                            "error",
                            f"door at {door.position} references unknown room '{ident}'",
                            door.span,
                        )
                    )
            elif kind == "corridor":
                if ident not in known_corridors:
                    diags.append(
                        _diag(
                            "error",
                            f"door at {door.position} references unknown corridor '{ident}'",
                            door.span,
                        )
                    )
            else:
                diags.append(
                    _diag(
                        "error",
                        f"door at {door.position} has malformed reference '{ref}'; "
                        f"expected 'room.NAME' or 'corridor.NAME'",
                        door.span,
                    )
                )
        if not _in_bounds(door.position, bw, bh):
            diags.append(
                _diag(
                    "warning",
                    f"door at {door.position} is outside the map bounds",
                    door.span,
                )
            )

    # ---- duplicate doors (two doors joining the same pair of nodes) ----
    seen_pairs: dict[frozenset, tuple] = {}
    for door in dmap.doors:
        valid = []
        for ref in door.connects:
            kind, _, ident = ref.partition(".")
            if (kind == "room" and ident in known_rooms) or (
                kind == "corridor" and ident in known_corridors
            ):
                valid.append(ref)
        if len(valid) != 2:
            continue  # boundary exits / multi-refs aren't "duplicates"
        pair = frozenset(valid)
        if pair in seen_pairs:
            a, b = sorted(valid)
            diags.append(
                _diag(
                    "warning",
                    f"door at {door.position} duplicates the connection "
                    f"{a} ↔ {b} (already joined by a door at {seen_pairs[pair]})",
                    door.span,
                )
            )
        else:
            seen_pairs[pair] = door.position

    # ---- windows ----
    for win in dmap.windows:
        if not win.in_ref:
            diags.append(
                _diag("error", f"window at {win.position} is missing `in`", win.span)
            )
        else:
            kind, _, ident = win.in_ref.partition(".")
            if kind == "room" and ident not in known_rooms:
                diags.append(
                    _diag(
                        "error",
                        f"window at {win.position} is in unknown room '{ident}'",
                        win.span,
                    )
                )
            elif kind == "corridor" and ident not in known_corridors:
                diags.append(
                    _diag(
                        "error",
                        f"window at {win.position} is in unknown corridor '{ident}'",
                        win.span,
                    )
                )
            elif kind not in ("room", "corridor"):
                diags.append(
                    _diag(
                        "error",
                        f"window at {win.position} has malformed `in` ref '{win.in_ref}'",
                        win.span,
                    )
                )
        if not _in_bounds(win.position, bw, bh):
            diags.append(
                _diag(
                    "warning",
                    f"window at {win.position} is outside the map bounds",
                    win.span,
                )
            )

    # ---- text annotations ----
    for ta in dmap.texts:
        if ta.size <= 0:
            diags.append(
                _diag(
                    "error",
                    f"text '{ta.text}' has non-positive size ({ta.size})",
                    ta.span,
                )
            )
        if not _in_bounds(ta.position, bw, bh):
            diags.append(
                _diag(
                    "warning",
                    f"text '{ta.text}' at {ta.position} is outside the "
                    f"map bounds",
                    ta.span,
                )
            )

    # ---- areas (decorative terrain) ----
    def check_area(a, *, scope: str) -> None:
        where = "" if scope == "map" else f" in {scope}"
        if isinstance(a.shape, PolygonRoom) and len(a.shape.points) < 3:
            diags.append(
                _diag(
                    "error",
                    f"area '{a.name}'{where} polygon has only "
                    f"{len(a.shape.points)} point(s); need at least 3",
                    a.span,
                )
            )
        if a.kind not in KNOWN_AREA_KINDS:
            diags.append(
                _diag(
                    "warning",
                    f"area '{a.name}'{where} has unknown kind '{a.kind}'; "
                    f"it renders in a neutral fallback colour. Known kinds: "
                    f"{', '.join(sorted(KNOWN_AREA_KINDS))}",
                    a.span,
                )
            )

    for a in dmap.areas:
        check_area(a, scope="map")

    # ---- line features (bars / curtain / barred) ----
    def check_line_feature(lf, *, scope: str) -> None:
        where = "" if scope == "map" else f" in {scope}"
        if len(lf.points) < 2:
            diags.append(
                _diag(
                    "error",
                    f"line_feature '{lf.name}'{where} has "
                    f"{len(lf.points)} point(s); need at least 2",
                    lf.span,
                )
            )
        if lf.kind not in KNOWN_LINE_FEATURE_KINDS:
            diags.append(
                _diag(
                    "warning",
                    f"line_feature '{lf.name}'{where} has unknown kind "
                    f"'{lf.kind}'; renders as a plain line. Known kinds: "
                    f"{', '.join(sorted(KNOWN_LINE_FEATURE_KINDS))}",
                    lf.span,
                )
            )
        for p in lf.points:
            if not _in_bounds(p, bw, bh):
                diags.append(
                    _diag(
                        "warning",
                        f"line_feature '{lf.name}'{where} point {p} is "
                        f"outside the map bounds ({bw} x {bh})",
                        lf.span,
                    )
                )

    for lf in dmap.line_features:
        check_line_feature(lf, scope="map")

    # ---- layers ----
    for layer in dmap.layers:
        for fi in layer.features:
            check_feature_inst(fi, scope=f"layer '{layer.name}'")
        for a in layer.areas:
            check_area(a, scope=f"layer '{layer.name}'")
        for lf in layer.line_features:
            check_line_feature(lf, scope=f"layer '{layer.name}'")

    # ---- overlapping areas (warning) ----
    # Compared only within a scope: top-level rooms/corridors together, and
    # each layer separately. Areas across layers (e.g. a hidden room beneath
    # a visible one) overlap by design and are not flagged.
    def _overlap_scope(
        rooms: dict[str, Room] | list[Room],
        corridors: dict[str, Corridor] | list[Corridor],
        scope: str,
    ) -> None:
        room_items = rooms.items() if isinstance(rooms, dict) else (
            (r.name, r) for r in rooms
        )
        corr_items = corridors.items() if isinstance(corridors, dict) else (
            (c.name, c) for c in corridors
        )
        areas: list[Area] = []
        spans: dict[str, SourceSpan] = {}
        # Labels opted out of the overlap warning via `allow_overlap`. A pair
        # is skipped if either side is exempt (deliberate stacking).
        exempt: set[str] = set()
        for name, room in room_items:
            label = f"room '{name}'"
            areas.append(Area(label=label, polygons=[room_polygon(room)]))
            spans[label] = room.span
            if room.allow_overlap:
                exempt.add(label)
        for name, corr in corr_items:
            label = f"corridor '{name}'"
            areas.append(Area(label=label, polygons=corridor_polygons(corr)))
            spans[label] = corr.span
        for la, lb, area in find_overlapping_areas(areas, min_area=OVERLAP_MIN_AREA):
            if la in exempt or lb in exempt:
                continue
            where = f" in {scope}" if scope else ""
            diags.append(
                _diag(
                    "warning",
                    f"{la} overlaps {lb}{where} by ~{area:.1f} sq units; "
                    f"their interiors intersect (adjoining walls are fine — "
                    f"this looks like a misplacement)",
                    spans.get(la),
                )
            )

    _overlap_scope(dmap.rooms, dmap.corridors, "")
    for layer in dmap.layers:
        _overlap_scope(layer.rooms, layer.corridors, f"layer '{layer.name}'")

    return diags
