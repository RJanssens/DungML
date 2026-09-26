"""Corridor wall geometry (`dungml.walls`).

A corridor is a polygon (its centreline buffered by half its width plus half
a wall stroke, so the wall line sits where the old stroked band's centre
did). Its walls are that polygon's outline. Where a corridor ends at a door,
the end is snapped — extended or trimmed — onto the wall the door sits on,
so the corridor's end wall and the host wall coincide and the door cuts one
door-wide opening through both. Openings exist only at doors and exits:
spaces that merely overlap stay layered (an overpass), because the graph
says they aren't connected.
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon

from dungml import parse
from dungml.walls import corridor_outlines

WS = 0.18  # wall stroke
HEAD = 'map "M" { grid { bounds 40 x 30 } }\n'


def _outlines(body: str):
    return corridor_outlines(parse(HEAD + body), wall_stroke=WS)


def _walls(o) -> list[LineString]:
    return [LineString(p) for p in o.wall_paths]


def _wall_hits(o, pt, tol=0.05) -> bool:
    return any(w.distance(Point(pt)) < tol for w in _walls(o))


STRAIGHT = """
room "a" { rect 2,4 12 x 10 }
room "b" { rect 18,4 10 x 10 }
corridor "k" { width 2 segment line from 14,9 to 18,9 }
door at 14,9 { connects room.a, corridor.k }
door at 18,9 { connects room.b, corridor.k }
"""


def test_straight_corridor_between_doors_is_a_clean_rectangle() -> None:
    o = _outlines(STRAIGHT)["k"]
    r = 1 + WS / 2
    minx, miny, maxx, maxy = o.polygon.bounds
    assert (minx, maxx) == (14, 18)  # ends exactly on the room walls
    assert math.isclose(miny, 9 - r) and math.isclose(maxy, 9 + r)
    assert math.isclose(o.polygon.area, 4 * 2 * r)


def test_door_cuts_a_door_wide_gap_in_the_corridor_end_wall() -> None:
    o = _outlines(STRAIGHT)["k"]
    # Inside the 1-wide door gap: no wall. Beside it, the corridor (2 wide)
    # is still closed by its end wall — a narrow door stays narrow.
    assert not _wall_hits(o, (14, 9))
    assert not _wall_hits(o, (18, 9.4))
    assert _wall_hits(o, (14, 9.8))
    assert _wall_hits(o, (18, 8.2))


def test_dead_end_is_closed_by_a_wall() -> None:
    o = _outlines('corridor "k" { width 2 segment line from 5,5 to 15,5 }')["k"]
    assert _wall_hits(o, (5, 5)) and _wall_hits(o, (15, 5))


# A room whose east wall is the diagonal from (10,2) to (14,14).
OBLIQUE_ROOM = 'room "a" { polygon (2,2) (10,2) (14,14) (2,14) }\n'
DIAG = LineString([(10, 2), (14, 14)])


def _beyond_diagonal(poly) -> float:
    """Area of `poly` on the far (room) side of the diagonal wall."""
    far = Polygon([(10, 2), (14, 14), (-50, 14), (-50, 2)])
    return poly.intersection(far).area


def _on_diagonal(poly) -> float:
    return poly.boundary.intersection(DIAG.buffer(1e-6)).length


def test_corridor_meeting_an_oblique_wall_reaches_it_across_its_full_width() -> None:
    # Centreline hits the diagonal at y=8 → x = 10 + 4*(6/12) = 12.
    o = _outlines(
        OBLIQUE_ROOM
        + 'corridor "k" { width 2 segment line from 12,8 to 24,8 }\n'
        + "door at 12,8 { connects room.a, corridor.k }\n"
    )["k"]
    assert _beyond_diagonal(o.polygon) < 1e-6  # no overhang into the room
    r = 1 + WS / 2
    # The end edge lies on the wall: its length is the width / cos(angle).
    cos = abs((12 / math.hypot(4, 12)))  # wall direction vs corridor normal
    assert math.isclose(_on_diagonal(o.polygon), 2 * r / cos, rel_tol=1e-3)


def test_corridor_poking_into_the_room_is_trimmed_to_the_wall() -> None:
    o = _outlines(
        OBLIQUE_ROOM
        + 'corridor "k" { width 2 segment line from 11.2,8 to 24,8 }\n'
        + "door at 12,8 { connects room.a, corridor.k }\n"
    )["k"]
    assert _beyond_diagonal(o.polygon) < 1e-6
    assert _on_diagonal(o.polygon) > 2


def test_corridor_stopping_short_of_the_wall_is_extended_to_it() -> None:
    o = _outlines(
        OBLIQUE_ROOM
        + 'corridor "k" { width 2 segment line from 12.4,8 to 24,8 }\n'
        + "door at 12,8 { connects room.a, corridor.k }\n"
    )["k"]
    assert _beyond_diagonal(o.polygon) < 1e-6
    assert _on_diagonal(o.polygon) > 2


def test_t_junction_door_into_another_corridors_side() -> None:
    outs = _outlines(
        'corridor "a" { width 2 segment line from 2,10 to 30,10 }\n'
        'corridor "b" { width 2 segment line from 16,2 to 16,9 }\n'
        "door at 16,9 { connects corridor.a, corridor.b width 2 type open }\n"
    )
    a, b = outs["a"], outs["b"]
    r = 1 + WS / 2
    # b's end snapped onto a's near side wall (y = 10 - r).
    assert math.isclose(b.polygon.bounds[3], 10 - r)
    # The open door cuts both a's side wall and b's end wall.
    assert not _wall_hits(a, (16, 10 - r))
    assert not _wall_hits(b, (16, 10 - r))
    assert _wall_hits(a, (13, 10 - r))  # a's side wall elsewhere is intact


def test_exit_at_a_corridor_end_leaves_it_open() -> None:
    o = _outlines(
        'corridor "k" { width 2 segment line from 5,5 to 15,5 }\n'
        'exit at 15,5 { to "below" at 1,1 }\n'
    )["k"]
    assert not _wall_hits(o, (15, 5))
    assert _wall_hits(o, (5, 5))


def test_secret_door_at_a_corridor_end_keeps_it_closed() -> None:
    o = _outlines(STRAIGHT.replace(
        "door at 18,9 { connects room.b, corridor.k }",
        "door at 18,9 { connects room.b, corridor.k type secret }",
    ))["k"]
    assert _wall_hits(o, (18, 9))


def test_unconnected_crossing_corridors_stay_layered() -> None:
    outs = _outlines(
        'corridor "h" { width 2 segment line from 1,10 to 20,10 }\n'
        'corridor "v" { width 2 segment line from 10,2 to 10,18 }\n'
    )
    # No door, no opening: each keeps its walls through the crossing.
    r = 1 + WS / 2
    assert _wall_hits(outs["h"], (10, 10 + r))
    assert _wall_hits(outs["v"], (10 + r, 10))


def test_branches_of_one_corridor_merge_without_inner_walls() -> None:
    o = _outlines(
        'corridor "x" { width 2\n'
        "  node hub at 10,10 node n at 10,2 node e at 20,10 node s at 10,18\n"
        "  run hub to n run hub to e run hub to s }\n"
    )["x"]
    assert o.polygon.geom_type == "Polygon"
    walls = _walls(o)
    assert min(w.distance(Point(10, 10)) for w in walls) > 1 + WS / 2 - 1e-6


def test_straight_corners_are_mitred_and_round_corners_are_round() -> None:
    body = 'corridor "k" {{ width 2 {c} segment line from 5,5 to 15,5 segment line from 15,5 to 15,15 }}'
    sharp = _outlines(body.format(c="corners straight"))["k"].polygon
    round_ = _outlines(body.format(c="corners round"))["k"].polygon
    r = 1 + WS / 2
    outer = Point(15 + r, 5 - r)  # the outer corner of the bend
    assert sharp.buffer(1e-6).contains(outer)
    assert not round_.buffer(1e-6).contains(outer)


def test_door_on_a_room_corner_snaps_onto_both_walls() -> None:
    # goblin_warren's fissure: the door sits on the polygon's vertex (12,20)
    # where two walls meet, and the corridor arrives almost parallel to the
    # lower wall — its right edge never enters the room at all. So: the side
    # that does enter snaps onto the room's outline (round the corner, not
    # along one wall's line, which is what left a hook), the side that misses
    # ends where it was authored to, and nothing lies inside the room.
    room_pts = [(2, 18), (6, 16), (10, 17), (12, 20), (10, 23), (6, 24), (3, 22)]
    o = _outlines(
        "room \"f\" { polygon " + " ".join(f"({x},{y})" for x, y in room_pts) + " }\n"
        'corridor "k" { width 1.4 segment line from 12,20 to 16,12 }\n'
        "door at 12,20 { connects room.f, corridor.k type arch }\n"
    )["k"]
    room = Polygon(room_pts)
    r = 0.7 + WS / 2
    assert o.polygon.intersection(room).area < 1e-6  # nothing inside the room
    touching = o.polygon.boundary.intersection(room.boundary.buffer(1e-6)).length
    assert touching >= r  # the entering half rests on the room outline
    # The far corner of the missing side stays at the authored end: no
    # extension past the room's corner into the rock.
    assert o.polygon.bounds[3] <= 20 + r * 0.5


def test_door_on_a_circular_room_snaps_onto_the_curve() -> None:
    o = _outlines(
        'room "c" { circle at 10,10 radius 5 }\n'
        'corridor "k" { width 2 segment line from 15,10 to 25,10 }\n'
        "door at 15,10 { connects room.c, corridor.k }\n"
    )["k"]
    from dungml.geometry import circle_points

    circle = Polygon(circle_points((10, 10), 5))  # the 64-gon the renderer draws
    assert o.polygon.intersection(circle).area < 1e-3
    assert o.polygon.distance(circle) < 1e-6  # no gap between floor and room
