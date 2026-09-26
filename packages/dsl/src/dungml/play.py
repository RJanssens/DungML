"""Play-session helpers: fog-of-war rendering with a party-location marker.

Builds on `graph.fog_of_war` (which prunes a map to the discovered subset)
and the renderer's `party_start` marker (a disc drawn at a world point).
Pure functions — state (what's discovered, where the party is) lives in the
caller (the backend's PlaySession row / the MCP session store).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from .geometry import node_centroid
from . import walk
from .graph import Graph, build_graph, fog_of_war, keyed_doors
from .model import (
    Corridor,
    DungeonMap,
    LineSegment,
    PartyStart,
    Segment,
    Vec2,
)
from .render import get_renderer

_SVG_OPEN_RE = re.compile(r"<svg\b", re.IGNORECASE)


def _stamp_party_node(svg: str, node_id: str) -> str:
    """Add data-party-node to the root <svg> so a campaign-mode viewer can
    frame the party's room via its existing focus toggle."""
    esc = (
        node_id.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return _SVG_OPEN_RE.sub(f'<svg data-party-node="{esc}"', svg, count=1)


_STUB_LEN = 1.0  # one grid cell; a corridor's width is already one cell
_EPS = 1e-9


@dataclass(frozen=True)
class FadeStub:
    """A ~1-cell piece of an *unrevealed* corridor, drawn beyond an open
    junction and faded to transparent so the fog boundary reads softly
    instead of stopping dead."""

    segments: list[Segment]  # clipped line segments of the hidden corridor
    width: float
    fade_from: Vec2  # the junction — opaque end of the gradient
    fade_to: Vec2  # far end of the stub — transparent end of the gradient


def _dist(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def clip_corridor(
    corr: Corridor, start: Vec2, length: float
) -> list[LineSegment]:
    """Line segments covering `length` units of `corr`, measured from the
    endpoint nearest `start` and walking along connected segments (so a bend
    within the clip is followed). Returns [] if `corr` has no line geometry."""
    segs = [s for s in corr.segments if isinstance(s, LineSegment)]
    if not segs:
        return []
    # Entry = the segment endpoint closest to `start`, oriented outward.
    best: Optional[tuple[float, int, Vec2, Vec2]] = None
    for i, s in enumerate(segs):
        for a, b in ((s.start, s.end), (s.end, s.start)):
            d = _dist(a, start)
            if best is None or d < best[0]:
                best = (d, i, a, b)
    assert best is not None
    _, cur_i, cur_from, cur_to = best
    remaining = length
    used: set[int] = set()
    out: list[LineSegment] = []
    while remaining > _EPS:
        seg_len = _dist(cur_from, cur_to)
        if seg_len <= _EPS:
            break
        if seg_len >= remaining:
            t = remaining / seg_len
            cut = (
                cur_from[0] + t * (cur_to[0] - cur_from[0]),
                cur_from[1] + t * (cur_to[1] - cur_from[1]),
            )
            out.append(LineSegment(start=cur_from, end=cut))
            break
        out.append(LineSegment(start=cur_from, end=cur_to))
        remaining -= seg_len
        used.add(cur_i)
        nxt: Optional[tuple[int, Vec2, Vec2]] = None
        for j, s in enumerate(segs):
            if j in used:
                continue
            for a, b in ((s.start, s.end), (s.end, s.start)):
                if _dist(a, cur_to) <= 1e-6:
                    nxt = (j, a, b)
                    break
            if nxt is not None:
                break
        if nxt is None:
            break
        cur_i, cur_from, cur_to = nxt
    return out


def corridor_fade_stubs(
    dmap: DungeonMap, graph: Graph, discovered_nodes: Iterable[str]
) -> list[FadeStub]:
    """Fade stubs for every open corridor→corridor junction that leaves the
    discovered subset. Computed from the *full* map (before fog pruning).
    Deterministic order (sorted) so mask ids are stable across renders."""
    discovered = set(discovered_nodes)
    # Keyed as build_graph keys its edges (so the second of two doors stacked
    # at one point is found too); hidden-layer doors and corridors are left
    # out — a stub must never hint at GM-only geometry.
    pos_by_key: dict[str, Vec2] = {
        key: p.item.position for key, p in keyed_doors(dmap) if not p.hidden
    }
    corr_by_id: dict[str, Corridor] = {
        f"corridor.{name}": c for name, c in walk.corridors(dmap, visible=True).items()
    }

    stubs: list[FadeStub] = []
    for node_id in sorted(discovered):
        if not node_id.startswith("corridor."):
            continue
        for nbr, edge in sorted(
            graph.neighbors(node_id), key=lambda ne: (ne[0], ne[1].key)
        ):
            if nbr in discovered or not nbr.startswith("corridor."):
                continue
            if edge.hidden or edge.type != "open":
                continue
            junction = pos_by_key.get(edge.key)
            hidden = corr_by_id.get(nbr)
            if junction is None or hidden is None:
                continue
            segs = clip_corridor(hidden, junction, _STUB_LEN)
            if not segs:
                continue
            stubs.append(
                FadeStub(
                    segments=list(segs),
                    width=hidden.width,
                    fade_from=junction,
                    fade_to=segs[-1].end,
                )
            )
    return stubs


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
    revealed: Iterable[str] = (),
) -> str:
    """Render a play view.

    With `full=False` (default) the map is pruned to the discovered subset
    via `fog_of_war`, giving the players' view. With `full=True` the whole
    map is drawn (the GM's view) — handy for showing the party marker on the
    complete map. Either way, when `party_location` is a known node, a start
    marker is drawn at its centroid to track where the party is. `revealed`
    is the DM's reveal list: secrets shown to the players (see
    `dungml.secrets`).
    """
    if full:
        view = dmap.model_copy(deep=True)
    else:
        view = fog_of_war(dmap, discovered_nodes, discovered_doors, revealed)
    pos = node_centroid(view, party_location) if party_location else None
    if pos is not None:
        view.map.party_start = PartyStart(at=pos)
    name = renderer or view.map.renderer
    r = get_renderer(name)()
    if not full:
        r.fade_stubs = corridor_fade_stubs(dmap, build_graph(dmap), discovered_nodes)
    svg = r.render(view)
    if pos is not None and party_location:
        svg = _stamp_party_node(svg, party_location)
    return svg
