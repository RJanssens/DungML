"""Semantic validation pass over a parsed DungeonMap.

Catches what the grammar cannot: dangling references, duplicate names,
polygons with too few points, doors connecting to non-existent rooms,
window/door positions outside the map bounds, etc.

Validation is *additive* — it returns a list of Diagnostics. Callers
decide whether to treat warnings as fatal.
"""
from __future__ import annotations

import difflib

from . import walk
from .builtins import BUILTIN_FEATURES
from .errors import Diagnostic
from .geometry import Area, corridor_polygons, find_overlapping_areas, room_polygon
from .graph import build_graph
from .render.theme import list_themes
from .secrets import list_secrets

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
KNOWN_LINE_FEATURE_KINDS = {"bars", "curtain", "barred", "step"}
# Door types with their own glyph or graph meaning, plus the documented
# materials (which draw a plain leaf). Aliases are the spellings the renderer
# and `graph` already special-case.
KNOWN_DOOR_TYPES = frozenset({
    "wooden", "iron", "stone",
    "secret", "concealed", "hidden",
    "open", "opening", "gap",
    "arch", "archway", "smashed", "broken",
    "portcullis", "gate", "gates",
    "double", "double-door", "double_door",
    "one-way", "oneway", "one_way",
})
# Authored states, the blocking ones `graph.BLOCKING_STATES` understands, and
# the runtime words play sessions record.
KNOWN_DOOR_STATES = frozenset({
    "closed", "open", "ajar", "unlocked", "trapped",
    "locked", "barred", "stuck", "sealed",
    "opened", "forced", "broken",
})
KNOWN_LINE_STYLES = frozenset({"solid", "organic", "ruined", "dotted", "dashed", "trail"})
KNOWN_CORNERS = frozenset({"round", "straight"})
from .model import (
    BoundaryRoom,
    CircleRoom,
    Corridor,
    Door,
    DungeonMap,
    FeatureInstance,
    GlyphPolygon,
    GlyphPolyline,
    PolygonRoom,
    PolygonShape,
    RectRoom,
    Room,
    SourceSpan,
    Window,
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


def _duplicate(kind: str, name: str, first: SourceSpan, again: SourceSpan) -> Diagnostic:
    where = f" (first defined on line {first.line})" if first.line else ""
    return _diag(
        "warning",
        f"duplicate {kind} '{name}'{where}: only one definition is used, "
        f"the other is silently dropped",
        again,
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
    known_rooms = set(walk.rooms(dmap))
    known_corridors = set(walk.corridors(dmap))
    all_doors = [p.item for p in walk.members(dmap, "doors")]

    ps = dmap.map.party_start
    if ps is not None and ps.ref is not None:
        if ps.ref not in known_rooms and ps.ref not in known_corridors:
            diags.append(
                _diag(
                    "error",
                    f"party_start references unknown room/corridor '{ps.ref}'",
                    dmap.map.span,
                )
            )

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

    # ---- misspelt enum values (warnings: unknown values still render) ----
    def check_choice(
        value: str | None, known: frozenset[str], what: str, span: SourceSpan
    ) -> None:
        if value is None or value.lower() in known:
            return
        close = difflib.get_close_matches(value.lower(), sorted(known), n=1)
        hint = f"; did you mean '{close[0]}'?" if close else ""
        diags.append(
            _diag(
                "warning",
                f"{what} '{value}' is not recognised{hint} "
                f"(known: {', '.join(sorted(known))})",
                span,
            )
        )

    def check_line_style(value: str | None, owner: str, span: SourceSpan) -> None:
        check_choice(value, KNOWN_LINE_STYLES, f"{owner} line_style", span)

    # ---- rooms ----
    def check_room(name: str, room: Room, *, layer: str | None) -> None:
        where = f" in layer '{layer}'" if layer else ""
        scope = f"layer '{layer}' room '{name}'" if layer else f"room '{name}'"
        if isinstance(room.shape, RectRoom):
            if room.shape.width <= 0 or room.shape.height <= 0:
                diags.append(
                    _diag(
                        "error",
                        f"room '{name}'{where} has non-positive dimensions "
                        f"({room.shape.width} x {room.shape.height})",
                        room.span,
                    )
                )
        elif isinstance(room.shape, PolygonRoom):
            if len(room.shape.points) < 3:
                diags.append(
                    _diag(
                        "error",
                        f"room '{name}'{where} polygon has only "
                        f"{len(room.shape.points)} point(s); need at least 3",
                        room.span,
                    )
                )
        elif isinstance(room.shape, BoundaryRoom):
            if len(room.shape.edges) < 2:
                diags.append(
                    _diag(
                        "error",
                        f"room '{name}'{where} boundary has only "
                        f"{len(room.shape.edges)} edge(s); need at least 2",
                        room.span,
                    )
                )
        elif isinstance(room.shape, CircleRoom):
            if room.shape.radius <= 0:
                diags.append(
                    _diag(
                        "error",
                        f"room '{name}'{where} has non-positive radius "
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
                        f"room '{name}'{where} label position "
                        f"{room.label.position} is outside the map bounds",
                        room.span,
                    )
                )
        check_line_style(room.line_style, f"room '{name}'{where}", room.span)
        for fi in room.features:
            check_feature_inst(fi, scope=scope)
        for ex in room.exits:
            check_exit(ex, scope=scope)
        for lf in room.line_features:
            check_line_feature(lf, scope=scope)
        for a in room.areas:
            check_area(a, scope=scope)
        for ta in room.texts:
            check_text(ta)

    # ---- corridors ----
    def check_corridor(name: str, corr: Corridor, *, layer: str | None) -> None:
        where = f" in layer '{layer}'" if layer else ""
        scope = f"layer '{layer}' corridor '{name}'" if layer else f"corridor '{name}'"
        # width 0 is allowed — it renders as a single centerline (a route /
        # passage line). Only a negative width is an error.
        if corr.width < 0:
            diags.append(
                _diag(
                    "error",
                    f"corridor '{name}'{where} has negative width ({corr.width})",
                    corr.span,
                )
            )
        if not corr.segments:
            diags.append(
                _diag("warning", f"corridor '{name}'{where} has no segments", corr.span)
            )
        check_line_style(corr.line_style, f"corridor '{name}'{where}", corr.span)
        check_choice(
            corr.corners, KNOWN_CORNERS, f"corridor '{name}'{where} corners", corr.span
        )
        for fi in corr.features:
            check_feature_inst(fi, scope=scope)
        for ex in corr.exits:
            check_exit(ex, scope=scope)
        for lf in corr.line_features:
            check_line_feature(lf, scope=scope)
        for a in corr.areas:
            check_area(a, scope=scope)
        for ta in corr.texts:
            check_text(ta)

    # ---- doors ----
    def check_door(door: Door) -> None:
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
        check_choice(
            door.type, KNOWN_DOOR_TYPES, f"door at {door.position}: door type", door.span
        )
        check_choice(
            door.state, KNOWN_DOOR_STATES, f"door at {door.position}: door state", door.span
        )

    # ---- windows ----
    def check_window(win: Window) -> None:
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
    def check_text(ta) -> None:
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
        check_line_style(a.line_style, f"area '{a.name}'{where}", a.span)
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

    # ---- exits (cross-map transitions) ----
    # The target map lives elsewhere in the project, so we can't verify it
    # (or the landing coordinates) here — that's a whole-project concern the
    # backend resolves. We only check what's local: a non-empty target and an
    # in-bounds placement.
    def check_exit(ex, *, scope: str) -> None:
        where = "" if scope == "map" else f" in {scope}"
        if not ex.target_map.strip():
            diags.append(
                _diag(
                    "error",
                    f"exit at {ex.position}{where} has an empty target map name",
                    ex.span,
                )
            )
        if not _in_bounds(ex.position, bw, bh):
            diags.append(
                _diag(
                    "warning",
                    f"exit at {ex.position}{where} is outside the map bounds "
                    f"({bw} x {bh})",
                    ex.span,
                )
            )

    # ---- walk every scope: top level, then each layer ----
    for fi in dmap.features:
        check_feature_inst(fi, scope="map")
    for a in dmap.areas:
        check_area(a, scope="map")
    for lf in dmap.line_features:
        check_line_feature(lf, scope="map")
    for ex in dmap.exits:
        check_exit(ex, scope="map")
    for ta in dmap.texts:
        check_text(ta)
    for name, room in dmap.rooms.items():
        check_room(name, room, layer=None)
    for name, corr in dmap.corridors.items():
        check_corridor(name, corr, layer=None)
    for door in dmap.doors:
        check_door(door)
    for win in dmap.windows:
        check_window(win)
    for layer in dmap.layers:
        scope = f"layer '{layer.name}'"
        for fi in layer.features:
            check_feature_inst(fi, scope=scope)
        for a in layer.areas:
            check_area(a, scope=scope)
        for lf in layer.line_features:
            check_line_feature(lf, scope=scope)
        for ex in layer.exits:
            check_exit(ex, scope=scope)
        for ta in layer.texts:
            check_text(ta)
        for room in layer.rooms:
            check_room(room.name, room, layer=layer.name)
        for corr in layer.corridors:
            check_corridor(corr.name, corr, layer=layer.name)
        for door in layer.doors:
            check_door(door)
        for win in layer.windows:
            check_window(win)
    check_choice(
        dmap.map.default_corners, KNOWN_CORNERS, "map corners", dmap.map.span
    )
    check_choice(
        dmap.map.theme, frozenset(list_themes()), "map theme", dmap.map.span
    )

    # ---- duplicate doors (two doors joining the same pair of nodes) ----
    seen_pairs: dict[frozenset, tuple] = {}
    for door in all_doors:
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

    # ---- door names: two doors with one name share one key ----
    named: dict[str, list] = {}
    for d in all_doors:
        if d.id:
            named.setdefault(d.id, []).append(d)
    for name, same in named.items():
        for d in same[1:]:
            diags.append(
                _diag(
                    "warning",
                    f"door '{name}' is named {len(same)} times; play sessions track "
                    f"doors by name, so they would be found and opened together",
                    d.span,
                )
            )

    # ---- secret keys: two secrets sharing a key are revealed together ----
    by_key: dict[str, list] = {}
    for sc in list_secrets(dmap):
        by_key.setdefault(sc.key, []).append(sc)
    for key, same in by_key.items():
        for sc in same[1:]:
            diags.append(
                _diag(
                    "warning",
                    f"secret key '{key}' is shared by {len(same)} secrets; revealing "
                    f"one reveals them all — give each its own `id`",
                    sc.item.span,
                )
            )

    # ---- duplicate names ----
    # Same-file redefinitions (recorded by the parser — the model keeps only
    # the last), then top-level vs layer and layer vs layer. The renderer and
    # graph silently use one of each pair, so the other simply vanishes.
    # (A main-file feature_def overriding an included one is intended and
    # never reaches here: includes merge first-definition-wins.)
    for kind, name, first, again in dmap._redefinitions:
        diags.append(_duplicate(kind, name, first, again))
    for kind, top, layered in (
        ("room", dmap.rooms, [r for layer in dmap.layers for r in layer.rooms]),
        ("corridor", dmap.corridors, [c for layer in dmap.layers for c in layer.corridors]),
    ):
        seen: dict[str, SourceSpan] = {n: e.span for n, e in top.items()}
        for e in layered:
            if e.name in seen:
                diags.append(_duplicate(kind, e.name, seen[e.name], e.span))
            else:
                seen[e.name] = e.span

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

    # ---- connectivity: a map the party can't walk across is usually a
    # missing door, not intent. Warnings, because a cave reached only by a
    # map `exit` is legitimate. Nodes in hidden layers still count — the GM
    # authored them and they still need to be reachable in play.
    g = build_graph(dmap)
    if g.nodes:
        # Undirected adjacency, built once: a one-way door still physically
        # connects two nodes, so connectivity ignores its direction.
        undirected: dict[str, set[str]] = {nid: set() for nid in g.nodes}
        for e in g.edges:
            undirected[e.a].add(e.b)
            undirected[e.b].add(e.a)

        seen: set[str] = set()
        parts: list[list[str]] = []
        for start in sorted(g.nodes):
            if start in seen:
                continue
            comp, stack = [], [start]
            seen.add(start)
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for nxt in undirected.get(cur, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            parts.append(sorted(comp))
        if len(parts) > 1:
            names = "; ".join(
                ", ".join(p[:3]) + (" …" if len(p) > 3 else "") for p in parts
            )
            diags.append(
                _diag(
                    "warning",
                    f"map is not connected: {len(parts)} separate parts ({names})",
                )
            )

        for nid, node in g.nodes.items():
            if node.kind != "corridor":
                continue
            doors = {e.key for e in g.incident_edges(nid)} | {
                b.key for b in g.boundary_exits(nid)
            }
            doors |= {e.key for e in g.edges if e.b == nid and e.one_way}
            if len(doors) == 1:
                diags.append(
                    _diag(
                        "warning",
                        f"corridor '{node.name}' has only one door — a dead end",
                    )
                )

    return diags
