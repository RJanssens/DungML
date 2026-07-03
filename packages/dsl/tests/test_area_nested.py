"""`area` blocks authored inside room / corridor blocks.

The nesting binds the area to its node (absolute coords): it stays on the
room/corridor and is NOT hoisted to the map level, so — like a nested text —
it renders only when that node is visible (fog prunes the node and its area
together).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from dungml import Area, parse, render, render_fogged


def test_area_nested_in_room_stays_on_room_not_hoisted() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    room "hall" {
      rect 2,2 10 x 8
      area "pool" kind water { rect 4,4 3 x 3 }
    }
    """
    m = parse(src)
    # Kept on the room...
    assert len(m.rooms["hall"].areas) == 1
    a = m.rooms["hall"].areas[0]
    assert isinstance(a, Area)
    assert a.name == "pool"
    assert a.kind == "water"
    # ...and NOT hoisted to the map level.
    assert len(m.areas) == 0


def test_area_nested_in_corridor() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    corridor "c" {
      width 2
      segment line from 12,6 to 24,6
      area "spill" kind lava { rect 16,5 3 x 2 }
    }
    """
    c = parse(src).corridors["c"]
    assert len(c.areas) == 1
    assert c.areas[0].name == "spill"
    assert c.areas[0].kind == "lava"


def test_top_level_area_still_lands_on_map() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    area "lake" kind water { rect 1,1 4 x 4 }
    room "hall" { rect 10,2 8 x 8 }
    """
    m = parse(src)
    assert len(m.areas) == 1
    assert len(m.rooms["hall"].areas) == 0


def _area_count(svg: str) -> int:
    root = ET.fromstring(svg)
    return sum(1 for e in root.iter() if e.get("class") == "area")


def test_nested_area_renders() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    room "hall" {
      rect 2,2 10 x 8
      area "pool" kind water { rect 4,4 3 x 3 }
    }
    """
    assert _area_count(render(parse(src))) == 1


def test_nested_area_hidden_when_room_undiscovered() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    room "a" { rect 2,2 8 x 8 }
    room "b" { rect 18,2 8 x 8
      area "pit" kind pit { rect 20,4 3 x 3 }
    }
    door at 10,5 { connects room.a, room.b }
    """
    m = parse(src)
    # room.b not discovered → its nested area is absent from the players' view.
    hidden = render_fogged(m, {"room.a"}, set(), party_location="room.a")
    assert _area_count(hidden) == 0
    # room.b discovered → its nested area shows.
    shown = render_fogged(m, {"room.a", "room.b"}, {"10,5"}, party_location="room.a")
    assert _area_count(shown) == 1
