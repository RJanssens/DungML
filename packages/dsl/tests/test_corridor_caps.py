"""Dead-end corridors are closed by a wall across the end.

A degree-1 terminal endpoint (a true free end, not a bend / branch /
junction) is closed by the corridor's own outline; an end with a door is
snapped onto the door's wall and opened door-wide instead. (Formerly a
separate `corridor-cap` quad; now simply part of the outline — see
test_walls.py.)
"""
from __future__ import annotations

from shapely.geometry import LineString, Point

from dungml import parse, render
from dungml.walls import corridor_outlines


def _closed(src: str, *points: tuple[float, float]) -> list[bool]:
    """For each point, whether a wall of corridor `c` passes through it."""
    o = corridor_outlines(parse(src), wall_stroke=0.18)["c"]
    walls = [LineString(p) for p in o.wall_paths]
    return [any(w.distance(Point(p)) < 0.05 for w in walls) for p in points]


def test_both_free_ends_are_closed() -> None:
    src = (
        'map "M" { grid { bounds 20 x 10 } renderer "classic-bw" }\n'
        'corridor "c" { width 1 segment line from 2,5 to 18,5 }\n'
    )
    assert _closed(src, (2, 5), (18, 5)) == [True, True]


def test_end_with_a_door_is_open_the_free_end_closed() -> None:
    src = (
        'map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }\n'
        'room "r" { rect 18,4 10 x 8 }\n'
        'corridor "c" { width 2 segment line from 2,8 to 18,8 }\n'
        "door at 18,8 { connects room.r, corridor.c }\n"
    )
    assert _closed(src, (2, 8), (18, 8)) == [True, False]


def test_doored_both_ends_are_both_open() -> None:
    src = (
        'map "M" { grid { bounds 40 x 16 } renderer "classic-bw" }\n'
        'room "a" { rect 2,4 8 x 8 }\n'
        'room "b" { rect 30,4 8 x 8 }\n'
        'corridor "c" { width 2 segment line from 10,8 to 30,8 }\n'
        "door at 10,8 { connects room.a, corridor.c }\n"
        "door at 30,8 { connects room.b, corridor.c }\n"
    )
    assert _closed(src, (10, 8), (30, 8)) == [False, False]


def test_bend_is_not_closed_only_the_two_free_ends() -> None:
    # An L-bend: the shared middle point is degree-2 — floor, not a wall.
    src = (
        'map "M" { grid { bounds 20 x 20 } renderer "classic-bw" }\n'
        'corridor "c" { width 1 '
        "segment line from 2,2 to 2,15 segment line from 2,15 to 15,15 }\n"
    )
    assert _closed(src, (2, 2), (2, 15), (15, 15)) == [True, False, True]


def test_zero_width_corridor_has_no_outline() -> None:
    # A zero-width corridor is a centerline/route marker — nothing to close.
    src = (
        'map "M" { grid { bounds 20 x 10 } renderer "classic-bw" }\n'
        'corridor "c" { width 0 segment line from 2,5 to 18,5 }\n'
    )
    assert "c" not in corridor_outlines(parse(src), wall_stroke=0.18)
    assert 'class="corridor-walls' not in render(parse(src))
