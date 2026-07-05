"""Fog-of-war fade stubs: a revealed corridor continuing into an unrevealed
corridor through an open junction gets a short, fading piece of the hidden
corridor drawn beyond the boundary."""
from __future__ import annotations

from dungml import parse
from dungml.graph import build_graph, door_key
from dungml.play import clip_corridor, corridor_fade_stubs

TWO = """
map "T" {
  grid { cell 32 px units feet 5 bounds 10 x 10 origin top-left }
  renderer "hatched"
}
corridor "a" {
  width 1
  node n1 at 1,5
  node n2 at 5,5
  run n1 to n2
}
corridor "b" {
  width 1
  node n1 at 5,5
  node n2 at 9,5
  run n1 to n2
}
door at 5,5 {
  connects corridor.a, corridor.b
  type open
}
"""
CLOSED = TWO.replace("type open", "type wooden")


def test_clip_corridor_follows_length():
    dmap = parse(TWO)
    segs = clip_corridor(dmap.corridors["b"], (5.0, 5.0), 1.0)
    assert len(segs) == 1
    assert segs[0].start == (5.0, 5.0)
    assert abs(segs[0].end[0] - 6.0) < 1e-6
    assert abs(segs[0].end[1] - 5.0) < 1e-6


def test_detects_open_corridor_to_corridor_stub():
    dmap = parse(TWO)
    stubs = corridor_fade_stubs(dmap, build_graph(dmap), {"corridor.a"})
    assert len(stubs) == 1
    s = stubs[0]
    assert s.fade_from == (5.0, 5.0)
    assert abs(s.fade_to[0] - 6.0) < 1e-6
    assert abs(s.fade_to[1] - 5.0) < 1e-6
    assert s.width == 1.0


def test_no_stub_when_neighbor_discovered():
    dmap = parse(TWO)
    stubs = corridor_fade_stubs(
        dmap, build_graph(dmap), {"corridor.a", "corridor.b"}
    )
    assert stubs == []


def test_no_stub_through_closed_door():
    dmap = parse(CLOSED)
    stubs = corridor_fade_stubs(dmap, build_graph(dmap), {"corridor.a"})
    assert stubs == []
