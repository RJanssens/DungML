"""Dead-end corridors are capped with a flat wall across the mouth.

A degree-1 terminal endpoint (a true free end, not a bend / branch /
junction) with no door or cross-map exit at it gets a `corridor-cap` quad;
ends that open via a connector stay open.
"""
from __future__ import annotations

from dungml import parse, render


def _caps(src: str) -> int:
    return render(parse(src)).count("corridor-cap")


def test_both_ends_open_are_both_capped() -> None:
    src = (
        'map "M" { grid { bounds 20 x 10 } renderer "classic-bw" }\n'
        'corridor "c" { width 1 segment line from 2,5 to 18,5 }\n'
    )
    assert _caps(src) == 2


def test_end_with_a_door_is_not_capped() -> None:
    src = (
        'map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }\n'
        'room "r" { rect 18,4 10 x 8 }\n'
        'corridor "c" { width 2 segment line from 2,8 to 18,8 }\n'
        "door at 18,8 { connects room.r, corridor.c }\n"
    )
    # Only the free (far) end is capped.
    assert _caps(src) == 1


def test_doored_both_ends_has_no_caps() -> None:
    src = (
        'map "M" { grid { bounds 40 x 16 } renderer "classic-bw" }\n'
        'room "a" { rect 2,4 8 x 8 }\n'
        'room "b" { rect 30,4 8 x 8 }\n'
        'corridor "c" { width 2 segment line from 10,8 to 30,8 }\n'
        "door at 10,8 { connects room.a, corridor.c }\n"
        "door at 30,8 { connects room.b, corridor.c }\n"
    )
    assert _caps(src) == 0


def test_bend_is_not_capped_only_the_two_free_ends() -> None:
    # An L-bend: the shared middle point is degree-2 and must not be capped.
    src = (
        'map "M" { grid { bounds 20 x 20 } renderer "classic-bw" }\n'
        'corridor "c" { width 1 '
        "segment line from 2,2 to 2,15 segment line from 2,15 to 15,15 }\n"
    )
    assert _caps(src) == 2


def test_zero_width_corridor_has_no_caps() -> None:
    # A zero-width corridor is a centerline/route marker — nothing to cap.
    src = (
        'map "M" { grid { bounds 20 x 10 } renderer "classic-bw" }\n'
        'corridor "c" { width 0 segment line from 2,5 to 18,5 }\n'
    )
    assert _caps(src) == 0
