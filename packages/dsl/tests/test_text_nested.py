"""`text` annotations authored inside room / corridor blocks.

The nesting binds the text to its node (absolute `at x,y` coords): it stays on
the room/corridor and is NOT hoisted to the map level, so — like a nested
feature — it renders only when that node is visible (fog prunes the node and
its text together).
"""
from __future__ import annotations

from dungml import parse, render, render_fogged


def test_text_nested_in_room_stays_on_room_not_hoisted() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    room "hall" {
      rect 2,2 10 x 8
      text "A" at 6,6 description "Altar of the Old Gods"
    }
    """
    m = parse(src)
    # Kept on the room...
    assert len(m.rooms["hall"].texts) == 1
    assert m.rooms["hall"].texts[0].description == "Altar of the Old Gods"
    # ...and NOT hoisted to the map level (it's bound to the room).
    assert len(m.texts) == 0
    # The room itself did NOT absorb the text's description.
    assert m.rooms["hall"].description is None
    # It still renders in the normal (GM) view.
    assert ">A<" in render(m)


def test_nested_text_hidden_when_room_undiscovered() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    room "a" { rect 2,2 8 x 8 }
    room "b" { rect 18,2 8 x 8
      text "Z" at 22,6 description "secret altar"
    }
    door at 10,5 { connects room.a, room.b }
    """
    m = parse(src)
    # room.b not discovered → its nested text is gone in the players' view.
    hidden = render_fogged(m, {"room.a"}, set(), party_location="room.a")
    assert ">Z<" not in hidden
    # room.b discovered → its nested text shows.
    shown = render_fogged(m, {"room.a", "room.b"}, {"10,5"}, party_location="room.a")
    assert ">Z<" in shown


def test_text_nested_in_corridor_keeps_its_own_description() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    corridor "c" {
      width 2
      segment line from 12,6 to 24,6
      description "A long hallway"
      text "B" at 18,6 size 1.5 description "Collapsed ceiling" dm_notes "trap"
    }
    """
    c = parse(src).corridors["c"]
    # The corridor's own description survives; the text's binds to the text.
    assert c.description == "A long hallway"
    assert len(c.texts) == 1
    assert c.texts[0].description == "Collapsed ceiling"
    assert c.texts[0].dm_notes == "trap"
    assert c.texts[0].size == 1.5


def test_text_block_form_top_level_and_nested() -> None:
    # The braced block form (like `exit at … { … }`) is interchangeable with
    # the inline form, both at top level and nested in a room/corridor.
    src = """
    map "M" { grid { bounds 40 x 40 } renderer "classic-bw" }
    text "D" at 12.5,26.5 {
      description "A glyph carved into wall. Touching it teleports to #24."
    }
    room "r" {
      rect 2,2 30 x 30
      text "E" at 8,8 { size 2 rotate 15 description "carved glyph" dm_notes "secret" }
    }
    """
    m = parse(src)
    top = next(t for t in m.texts if t.text == "D")
    assert top.position == (12.5, 26.5)
    assert top.description.startswith("A glyph carved")
    nested = m.rooms["r"].texts[0]
    assert (nested.size, nested.rotate) == (2.0, 15.0)
    assert nested.description == "carved glyph"
    assert nested.dm_notes == "secret"
    # The room did not absorb the text's modifiers.
    assert m.rooms["r"].description is None


def test_nested_text_renders_glyph_and_tooltip() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    room "hall" {
      rect 2,2 10 x 8
      text "A" at 6,6 description "Altar"
    }
    """
    svg = render(parse(src))
    assert ">A<" in svg
    assert 'data-description="Altar"' in svg
