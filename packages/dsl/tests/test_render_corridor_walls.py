"""The renderer draws corridors from `dungml.walls` outlines: a filled floor
plus `.wall` outline paths, instead of a dark stroked band patched at every
junction (dead-end caps, side-door erasers, oblique-mouth wedges)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from dungml import parse, render

SVG = "{http://www.w3.org/2000/svg}"
HEAD = 'include "core.dmap"\nmap "M" { grid { bounds 40 x 30 } }\n'
STRAIGHT = HEAD + """
room "a" { rect 2,4 12 x 10 }
room "b" { rect 18,4 10 x 10 }
corridor "k" { width 2 segment line from 14,9 to 18,9 }
door at 14,9 { connects room.a, corridor.k }
door at 18,9 { connects room.b, corridor.k }
corridor "dead" { width 2 segment line from 20,20 to 30,20 }
"""


def _root(src: str) -> ET.Element:
    return ET.fromstring(render(parse(src)))


def test_no_junction_patches_remain() -> None:
    svg = render(parse(STRAIGHT))
    for cls in ("corridor-cap", "corridor-mouth", "door-opening"):
        assert f'class="{cls}"' not in svg
    # The dark stroked wall band is gone too (fog fade stubs still use it).
    assert 'class="corridor-wall"' not in svg


def test_corridor_floor_is_a_filled_shape_the_editor_can_find() -> None:
    root = _root(STRAIGHT)
    floor = next(
        el for el in root.iter(f"{SVG}path")
        if el.get("data-corridor") == "k" and "corridor-floor" in (el.get("class") or "")
    )
    assert floor.get("fill") not in (None, "none")
    assert floor.get("stroke") == "none"


def test_corridor_walls_are_wall_paths_grouped_by_corridor() -> None:
    root = _root(STRAIGHT)
    group = next(
        el for el in root.iter(f"{SVG}g")
        if el.get("data-corridor") == "dead" and el.get("class", "").startswith("corridor-walls")
    )
    walls = [el for el in group.iter(f"{SVG}path") if el.get("class") == "wall"]
    # A dead end on both sides and no doors: one closed outline.
    assert len(walls) == 1 and walls[0].get("d").rstrip().endswith("Z")


def test_corridor_line_style_applies_to_its_walls() -> None:
    root = _root(HEAD + 'corridor "k" { width 2 line_style dashed segment line from 2,2 to 20,2 }')
    group = next(el for el in root.iter(f"{SVG}g") if el.get("data-corridor") == "k")
    assert "dashed" in group.get("class").split()


def test_corridor_to_corridor_door_draws_a_proper_door() -> None:
    src = HEAD + """
corridor "a" { width 1 segment line from 1,5 to 5,5 }
corridor "b" { width 1 segment line from 5,5 to 9,5 }
door at 5,5 { connects corridor.a, corridor.b type wooden }
"""
    door = next(el for el in _root(src).iter(f"{SVG}g") if el.get("class") == "door-instance")
    kinds = {el.tag.removeprefix(SVG) + "." + (el.get("class") or "") for el in door.iter()}
    assert "polygon.door-leaf" in kinds  # a leaf across the opening, not a lone circle
    assert not any(k.startswith("circle.") for k in kinds)
