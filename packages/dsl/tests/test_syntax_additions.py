"""Smaller syntax additions: several positions per feature, room-local
coordinates, three-point corridor arcs, and warnings for properties set
twice (where the last one used to win silently)."""
from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point

from dungml import DmapParseError, parse, validate
from dungml.model import ArcSegment
from dungml.walls import _arc_points

HEAD = 'include "core.dmap"\nmap "M" { grid { bounds 40 x 30 } }\n'


# ---- several positions ----

def test_one_feature_line_places_it_at_every_position() -> None:
    d = parse(HEAD + 'room "a" { rect 1,1 14 x 14 feature pillar at 4,6 4,12 12,6 12,12 rotate 45 }')
    feats = d.rooms["a"].features
    assert [f.position for f in feats] == [(4, 6), (4, 12), (12, 6), (12, 12)]
    assert {f.rotate for f in feats} == {45}  # modifiers apply to each
    assert len({f.span.line for f in feats}) == 1  # one statement, one source line


def test_several_positions_work_at_top_level_and_in_layers() -> None:
    d = parse(HEAD + "feature pillar at 1,1 2,2\n"
              'layer "L" { feature pillar at 3,3 4,4 5,5 }')
    assert len(d.features) == 2 and len(d.layers[0].features) == 3


# ---- room-local coordinates ----

def test_room_at_makes_its_contents_relative() -> None:
    d = parse(HEAD + """room "sanctum" at 18,4 {
  rect 0,0 10 x 10
  label "Sanctum" at 5,1
  feature statue at 5,3
  text "carving" at 2,2
  area "pool" kind water { rect 6,6 2 x 2 }
  line_feature "rail" { point 1,8 point 4,8 }
  exit at 9,9 { to "below" at 1,1 }
}""")
    r = d.rooms["sanctum"]
    assert (r.shape.position, r.shape.width) == ((18, 4), 10)
    assert r.label.position == (23, 5)
    assert r.features[0].position == (23, 7)
    assert r.texts[0].position == (20, 6)
    assert r.areas[0].shape.position == (24, 10)
    assert r.line_features[0].points == [(19, 12), (22, 12)]
    assert r.exits[0].position == (27, 13)
    assert r.exits[0].target_position == (1, 1)  # on the other map: untouched


def test_room_at_moves_polygon_circle_and_boundary_shapes() -> None:
    d = parse(HEAD + 'room "p" at 10,10 { polygon (0,0) (4,0) (4,4) }\n'
              'room "c" at 20,20 { circle at 1,1 radius 2 }\n'
              'room "b" at 5,5 { boundary { start 0,0 line to 4,0 arc to 0,4 via 3,3 } }')
    assert d.rooms["p"].shape.points == [(10, 10), (14, 10), (14, 14)]
    assert d.rooms["c"].shape.center == (21, 21)
    b = d.rooms["b"].shape
    assert b.start == (5, 5) and b.edges[1].end == (5, 9) and b.edges[1].via == (8, 8)


def test_between_doors_follow_a_moved_room() -> None:
    tail = ('room "a" at {x},2 {{ rect 0,0 8 x 8 }}\n'
            'room "b" at {x2},2 {{ rect 0,0 8 x 8 }}\n'
            "door between room.a and room.b {{}}")
    assert parse(HEAD + tail.format(x=2, x2=10)).doors[0].position == (10, 6)
    assert parse(HEAD + tail.format(x=12, x2=20)).doors[0].position == (20, 6)


# ---- three-point arcs ----

def test_corridor_arc_through_three_points() -> None:
    d = parse(HEAD + 'corridor "k" { segment arc from 0,10 to 10,10 via 5,5 }')
    seg = d.corridors["k"].segments[0]
    assert isinstance(seg, ArcSegment)
    assert seg.center == pytest.approx((5, 10)) and seg.radius == pytest.approx(5)
    pts = _arc_points(seg)
    assert pts[0] == pytest.approx((0, 10)) and pts[-1] == pytest.approx((10, 10))
    # The arc passes through `via`, not the other half of the circle.
    assert LineString(pts).distance(Point(5, 5)) < 0.05


def test_three_point_arc_bulging_the_other_way() -> None:
    d = parse(HEAD + 'slice "s" { kind river segment arc from 0,10 to 10,10 via 5,15 }')
    pts = _arc_points(d.slices["s"].segments[0])
    assert LineString(pts).distance(Point(5, 15)) < 0.05


def test_collinear_arc_points_are_a_parse_error() -> None:
    with pytest.raises(DmapParseError, match="collinear"):
        parse(HEAD + 'corridor "k" { segment arc from 0,0 to 10,0 via 5,0 }')


# ---- properties set twice ----

@pytest.mark.parametrize("body, what", [
    ('room "a" { rect 1,1 4 x 4 label "One" label "Two" }', "room 'a' sets `label` 2 times"),
    ('room "a" { rect 1,1 4 x 4 rect 5,5 2 x 2 }', "room 'a' sets `shape` 2 times"),
    ('corridor "k" { width 2 width 3 segment line from 1,1 to 5,1 }', "corridor 'k' sets `width` 2 times"),
    ('door at 1,1 { type iron type stone }', "door at (1.0, 1.0) sets `type` 2 times"),
    ('area "p" { kind water kind lava rect 1,1 2 x 2 }', "area 'p' sets `kind` 2 times"),
])
def test_a_property_set_twice_warns(body: str, what: str) -> None:
    warns = [d.message for d in validate(parse(HEAD + body)) if d.severity == "warning"]
    assert any(what in m for m in warns), warns


def test_repeatable_properties_do_not_warn() -> None:
    body = ('room "a" { rect 1,1 9 x 9 feature pillar at 2,2 feature pillar at 3,3 '
            'text "x" at 4,4 text "y" at 5,5 }')
    warns = [d.message for d in validate(parse(HEAD + body)) if "times" in d.message]
    assert warns == []


def test_map_block_property_set_twice_warns() -> None:
    src = 'map "M" { grid { bounds 10 x 10 } renderer "hatched" renderer "classic-bw" }'
    warns = [d.message for d in validate(parse(src))]
    assert any("map 'M' sets `renderer` 2 times" in m for m in warns), warns
