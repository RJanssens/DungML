"""Auto-placed room labels (`dungml.labels`) — labels with no `at`/`align`.

The anchor used to be the average of the room's vertices, which falls
outside an L-shaped (or any concave) room, and a label happily sat on top of
the statue in the middle of the floor. Now: a point inside the room where
the label's box fits, clear of the room's features, wrapped onto two lines
or shrunk when the room is too narrow. Explicit `at` / `align` labels are
left exactly where the author put them.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from shapely.geometry import Point, Polygon, box

from dungml import parse, render
from dungml.geometry import node_centroid
from dungml.labels import place_label, text_box

SVG = "{http://www.w3.org/2000/svg}"
L_ROOM = [(13, 2), (22, 2), (22, 4), (15, 4), (15, 12), (13, 12)]


def _rect(p) -> Polygon:
    w, h = text_box(p.lines, p.size)
    return box(p.x - w / 2, p.y - h / 2, p.x + w / 2, p.y + h / 2)


def test_label_in_an_l_shaped_room_sits_inside_it() -> None:
    room = Polygon(L_ROOM)
    p = place_label(room, None, "2. L-shaped gallery", 0.9)
    assert room.contains(_rect(p))


def test_label_steps_off_a_feature_in_the_middle() -> None:
    room = box(0, 0, 12, 8)
    statue = Point(6, 4).buffer(1.0)
    p = place_label(room, statue, "1. Shrine", 0.9)
    r = _rect(p)
    assert room.contains(r) and not r.intersects(statue)


def test_unobstructed_rectangular_room_keeps_its_centre() -> None:
    p = place_label(box(0, 0, 12, 8), None, "1. Hall", 0.9)
    assert (p.x, p.y) == (6, 4) and p.size == 0.9 and p.lines == ("1. Hall",)


def test_too_long_for_one_line_wraps() -> None:
    room = box(0, 0, 7, 6)
    p = place_label(room, None, "3. The Scriptorium of Saint Vellis", 0.9)
    assert len(p.lines) == 2
    assert room.contains(_rect(p))


def test_shrinking_stops_at_half_size() -> None:
    # 4 x 2 is too small for this label at any allowed size: it gets the
    # smallest (half size, wrapped) rather than shrinking into illegibility.
    room = box(0, 0, 4, 2)
    p = place_label(room, None, "4. Antechamber of Echoes", 0.9)
    assert abs(p.size - 0.9 * 0.5) < 1e-9 and len(p.lines) == 2


def test_a_very_cramped_room_shrinks_further_rather_than_overflow() -> None:
    # 5 wide: even wrapped at 70% the label would spill over the walls
    # (seen on the demo map). Past the normal steps, shrink until it fits —
    # down to half size.
    room = box(0, 0, 5, 4)
    p = place_label(room, None, "3. The Scriptorium of Saint Vellis", 0.9)
    assert 0.9 * 0.5 - 1e-9 <= p.size < 0.9 * 0.7
    assert room.buffer(-0.25).contains(_rect(p))


def test_placement_is_deterministic() -> None:
    room, statue = Polygon(L_ROOM), Point(14, 3).buffer(0.5)
    a = place_label(room, statue, "2. L-shaped gallery", 0.9)
    b = place_label(room, statue, "2. L-shaped gallery", 0.9)
    assert a == b


# ---- renderer integration ----

def _label(svg: str, text: str) -> ET.Element:
    return next(
        el for el in ET.fromstring(svg).iter(f"{SVG}text")
        if el.get("class") == "label" and text in "".join(el.itertext())
    )


def _translate(el: ET.Element) -> tuple[float, float]:
    m = re.search(r"translate\(([-\d.]+),([-\d.]+)\)", el.get("transform"))
    return float(m.group(1)), float(m.group(2))


def test_rendered_label_in_an_l_room_is_inside_it() -> None:
    pts = " ".join(f"({x},{y})" for x, y in L_ROOM)
    svg = render(parse(
        'map "M" { grid { bounds 30 x 20 } }\n'
        f'room "g" {{ polygon {pts} label "L-shaped gallery" }}\n'
    ))
    assert Polygon(L_ROOM).contains(Point(_translate(_label(svg, "L-shaped"))))


def test_rendered_label_avoids_the_rooms_statue() -> None:
    svg = render(parse(
        'include "core.dmap"\n'
        'map "M" { grid { bounds 30 x 20 } }\n'
        'room "s" { rect 0,0 12 x 8 label "Shrine" feature statue at 6,4 }\n'
    ))
    x, y = _translate(_label(svg, "Shrine"))
    assert (x, y) != (6, 4)
    assert Point(x, y).distance(Point(6, 4)) > 0.8


def test_wrapped_label_renders_as_two_lines() -> None:
    svg = render(parse(
        'map "M" { grid { bounds 30 x 20 } }\n'
        'room "s" { rect 0,0 7 x 6 label "The Scriptorium of Saint Vellis" }\n'
    ))
    spans = list(_label(svg, "Scriptorium").iter(f"{SVG}tspan"))
    assert len(spans) == 2


def test_explicit_positions_are_untouched() -> None:
    src = (
        'include "core.dmap"\n'
        'map "M" { grid { bounds 30 x 20 } }\n'
        'room "s" { rect 0,0 12 x 8 label "Shrine" at 6,4 feature statue at 6,4 }\n'
    )
    assert _translate(_label(render(parse(src)), "Shrine")) == (6, 4)


def test_party_marker_of_an_l_room_is_inside_it() -> None:
    pts = " ".join(f"({x},{y})" for x, y in L_ROOM)
    d = parse('map "M" { grid { bounds 30 x 20 } }\n' f'room "g" {{ polygon {pts} }}\n')
    assert Polygon(L_ROOM).contains(Point(node_centroid(d, "room.g")))
