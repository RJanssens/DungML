"""Tests for circular rooms (`circle at X,Y radius R`)."""
from __future__ import annotations

import math

from dungml import parse, render, validate
from dungml.geometry import room_polygon
from dungml.model import CircleRoom


def _circle_src(radius: float = 8.0) -> str:
    return f"""
    map "M" {{ grid {{ bounds 30 x 30 }} }}
    room "rotunda" {{ circle at 15,15 radius {radius} label "Rotunda" }}
    """


def test_circle_room_parses() -> None:
    r = parse(_circle_src()).rooms["rotunda"]
    assert isinstance(r.shape, CircleRoom)
    assert r.shape.center == (15, 15)
    assert r.shape.radius == 8


def test_circle_room_polygon_is_on_the_circle() -> None:
    r = parse(_circle_src()).rooms["rotunda"]
    pts = room_polygon(r)
    assert len(pts) >= 32
    for x, y in pts:
        assert math.isclose(math.hypot(x - 15, y - 15), 8, rel_tol=1e-6)


def test_circle_room_renders_without_error() -> None:
    svg = render(parse(_circle_src()))
    assert 'data-room="rotunda"' in svg


def test_non_positive_radius_is_an_error() -> None:
    diags = validate(parse(_circle_src(radius=0)))
    assert any(d.severity == "error" and "radius" in d.message for d in diags)


def test_overlapping_circle_and_rect_warn() -> None:
    src = """
    map "M" { grid { bounds 40 x 40 } }
    room "disc" { circle at 12,12 radius 6 }
    room "box"  { rect 10,10 8 x 8 }
    """
    warns = [d for d in validate(parse(src)) if "overlap" in d.message]
    assert len(warns) == 1


def test_separated_circles_do_not_warn() -> None:
    src = """
    map "M" { grid { bounds 60 x 30 } }
    room "a" { circle at 10,15 radius 5 }
    room "b" { circle at 40,15 radius 5 }
    """
    assert [d for d in validate(parse(src)) if "overlap" in d.message] == []
