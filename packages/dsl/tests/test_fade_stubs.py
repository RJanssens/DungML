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


from dungml.graph import fog_of_war
from dungml.render import get_renderer


def test_hatched_renders_stub_group_with_mask():
    dmap = parse(TWO)
    r = get_renderer("hatched")()
    r.fade_stubs = corridor_fade_stubs(dmap, build_graph(dmap), {"corridor.a"})
    svg = r.render(fog_of_war(dmap, {"corridor.a"}, set()))
    assert 'class="fade-stub"' in svg
    assert 'mask="url(#dungml-fade-0)"' in svg
    assert "linearGradient" in svg


def test_no_stubs_no_fade_markup():
    dmap = parse(TWO)
    r = get_renderer("hatched")()  # fade_stubs defaults to []
    svg = r.render(fog_of_war(dmap, {"corridor.a"}, set()))
    assert "dungml-fade" not in svg


from dungml.play import render_fogged


def test_render_fogged_emits_fade_stub():
    dmap = parse(TWO)
    dk = door_key(dmap.doors[0])
    svg = render_fogged(dmap, {"corridor.a"}, {dk}, full=False)
    assert 'class="fade-stub"' in svg
    assert "dungml-fade-0" in svg


def test_render_fogged_full_has_no_fade_stub():
    dmap = parse(TWO)
    dk = door_key(dmap.doors[0])
    svg = render_fogged(dmap, {"corridor.a"}, {dk}, full=True)
    assert "dungml-fade" not in svg


def test_stub_through_second_of_two_stacked_doors():
    # Two doors at one point: build_graph keys the second "5,5#2". The stub
    # lookup used bare position keys, so it missed that edge entirely.
    src = TWO.replace(
        "door at 5,5 {\n  connects corridor.a, corridor.b\n  type open\n}",
        "door at 5,5 {\n  connects corridor.a\n  type wooden\n}\n"
        "door at 5,5 {\n  connects corridor.a, corridor.b\n  type open\n}",
    )
    dmap = parse(src)
    assert [e.key for e in build_graph(dmap).edges] == ["5,5#2"]
    stubs = corridor_fade_stubs(dmap, build_graph(dmap), {"corridor.a"})
    assert len(stubs) == 1
    assert stubs[0].fade_from == (5.0, 5.0)


def test_no_stub_from_a_door_in_a_hidden_layer():
    src = TWO.replace(
        "door at 5,5 {\n  connects corridor.a, corridor.b\n  type open\n}",
        'layer "gm" hidden {\n door at 5,5 { connects corridor.a, corridor.b type open }\n}',
    )
    dmap = parse(src)
    assert corridor_fade_stubs(dmap, build_graph(dmap), {"corridor.a"}) == []
