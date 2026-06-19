"""Fog-of-war play helpers: render_fogged, visible_doors, node_centroid."""
from __future__ import annotations

from dungml import build_graph, node_centroid, parse, render_fogged, visible_doors

SRC = """
map "M" { grid { cell 20 px bounds 30 x 30 } renderer "classic-bw" }
room "a" { rect 0,0 6 x 6 label "A" }
room "b" { rect 12,0 6 x 6 label "B" }
corridor "c1" { width 1 node n1 at 6,3 node n2 at 12,3 run n1 to n2 }
door at 6,3 { connects room.a, corridor.c1 type wooden }
door at 12,3 { connects corridor.c1, room.b type wooden }
door at 3,0 { connects room.a type secret }
"""


def test_visible_doors_excludes_secret() -> None:
    g = build_graph(parse(SRC))
    keys = visible_doors(g, "room.a")
    assert "6,3" in keys  # wooden door to corridor
    assert "3,0" not in keys  # secret door stays hidden


def test_node_centroid_room_and_corridor() -> None:
    d = parse(SRC)
    cx, cy = node_centroid(d, "room.a")
    assert 0 < cx < 6 and 0 < cy < 6
    assert node_centroid(d, "corridor.c1") is not None
    assert node_centroid(d, "room.nope") is None


def test_render_fogged_hides_undiscovered() -> None:
    d = parse(SRC)
    svg = render_fogged(d, {"room.a"}, {"6,3"}, party_location="room.a")
    assert 'data-room="a"' in svg
    assert 'data-room="b"' not in svg  # B not discovered → hidden
    assert "party-start" in svg  # party marker drawn


def test_render_fogged_full_shows_all() -> None:
    d = parse(SRC)
    svg = render_fogged(d, {"room.a"}, {"6,3"}, party_location="room.a", full=True)
    assert 'data-room="a"' in svg and 'data-room="b"' in svg
    assert "party-start" in svg


def test_render_fogged_party_marker_optional() -> None:
    d = parse(SRC)
    svg = render_fogged(d, {"room.a"}, {"6,3"})
    assert "party-start" not in svg
