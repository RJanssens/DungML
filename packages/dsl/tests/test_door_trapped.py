"""The orthogonal `trapped` door flag: parse, render, fog-of-war hiding."""
from __future__ import annotations

from dungml import parse, render, render_fogged

SRC = """
map "M" { grid { cell 20 px bounds 20 x 12 } renderer "classic-bw" }
room "a" { rect 1,1 6 x 6 label "A" }
room "b" { rect 11,1 6 x 6 label "B" }
door at 7,4 { connects room.a, room.b type wooden state locked trapped }
door at 4,7 { connects room.a type wooden }
"""


def test_trapped_flag_is_orthogonal_to_state() -> None:
    d = parse(SRC)
    trap_door = next(x for x in d.doors if x.position == (7.0, 4.0))
    assert trap_door.state == "locked"  # state preserved
    assert trap_door.trapped is True  # flag set independently
    plain = next(x for x in d.doors if x.position == (4.0, 7.0))
    assert plain.trapped is False


def test_trapped_renders_a_mark_in_normal_view() -> None:
    svg = render(parse(SRC))
    # Two trap arms (the X) are drawn for the one trapped door.
    assert "trap" in svg.lower()


def test_fog_player_view_hides_trap_but_gm_view_shows_it() -> None:
    d = parse(SRC)
    nodes = {"room.a", "room.b"}
    doors = {"7,4"}
    player = render_fogged(d, nodes, doors, party_location="room.a")
    assert "trap" not in player.lower()  # players don't see undiscovered traps
    gm = render_fogged(d, nodes, doors, party_location="room.a", full=True)
    assert "trap" in gm.lower()  # GM full view shows it


def test_bare_trapped_on_closed_door() -> None:
    src = """
    map "M" { grid { bounds 20 x 12 } }
    room "a" { rect 1,1 6 x 6 }
    door at 7,4 { connects room.a type wooden trapped }
    """
    d = parse(src).doors[0]
    assert d.state == "closed" and d.trapped is True
