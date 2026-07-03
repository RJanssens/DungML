"""`area` blocks authored inside room / corridor blocks.

The nesting binds the area to its node (absolute coords): it stays on the
room/corridor and is NOT hoisted to the map level, so — like a nested text —
it renders only when that node is visible (fog prunes the node and its area
together).
"""
from __future__ import annotations

from dungml import Area, parse


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
