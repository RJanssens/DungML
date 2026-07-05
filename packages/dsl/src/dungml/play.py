"""Play-session helpers: fog-of-war rendering with a party-location marker.

Builds on `graph.fog_of_war` (which prunes a map to the discovered subset)
and the renderer's `party_start` marker (a disc drawn at a world point).
Pure functions — state (what's discovered, where the party is) lives in the
caller (the backend's PlaySession row / the MCP session store).
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from .geometry import node_centroid
from .graph import Graph, fog_of_war
from .model import DungeonMap, PartyStart
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
    pos = node_centroid(view, party_location) if party_location else None
    if pos is not None:
        view.map.party_start = PartyStart(at=pos)
    name = renderer or view.map.renderer
    svg = get_renderer(name)().render(view)
    if pos is not None and party_location:
        svg = _stamp_party_node(svg, party_location)
    return svg
