"""Door syntax additions: a `secret` flag, named doors, `between` placement.

- `secret` conceals any door, whatever it's made of (`type iron secret`);
  `type secret` keeps working as before.
- `door "name" …` gives a door a stable key: play sessions record found
  and opened doors by key, and a position key changes whenever the author
  nudges the door. (Adding a name to an existing door changes its key once.)
- `door between A and B` computes the door's position from the geometry
  and fills in `connects` — so a door follows the rooms it joins.
"""
from __future__ import annotations

import pytest

from dungml import DmapParseError, build_graph, parse, render, render_fogged, validate
from dungml.graph import door_key

HEAD = 'map "M" { grid { bounds 40 x 30 } }\n'
TWO_ROOMS = HEAD + 'room "a" { rect 2,2 8 x 8 }\nroom "b" { rect 10,2 8 x 8 }\n'


# ---- secret flag ----

def test_secret_flag_conceals_a_door_of_any_type() -> None:
    d = parse(TWO_ROOMS + "door at 10,6 { connects room.a, room.b type iron secret }")
    door = d.doors[0]
    assert door.type == "iron" and door.secret
    edge = build_graph(d).edges[0]
    assert edge.hidden  # not visible until found
    svg = render(d)
    assert 'class="door secret-door"' in svg  # drawn as the S marker for the GM


def test_secret_door_does_not_open_the_wall() -> None:
    wall_breaks = lambda src: render(parse(src)).count('class="wall"')
    plain = TWO_ROOMS + "door at 10,6 { connects room.a, room.b type iron }"
    secret = TWO_ROOMS + "door at 10,6 { connects room.a, room.b type iron secret }"
    assert wall_breaks(secret) < wall_breaks(plain)  # no gap cut → fewer pieces


def test_type_secret_still_works() -> None:
    d = parse(TWO_ROOMS + "door at 10,6 { connects room.a, room.b type secret }")
    assert build_graph(d).edges[0].hidden


# ---- named doors ----

def test_a_named_door_is_keyed_by_its_name() -> None:
    d = parse(TWO_ROOMS + 'door "vault" at 10,6 { connects room.a, room.b }')
    assert d.doors[0].id == "vault"
    assert door_key(d.doors[0]) == "vault"
    assert build_graph(d).edges[0].key == "vault"


def test_moving_a_named_door_keeps_its_session_state() -> None:
    before = parse(TWO_ROOMS + 'door "vault" at 10,6 { connects room.a, room.b }')
    after = parse(TWO_ROOMS + 'door "vault" at 10,4 { connects room.a, room.b }')
    assert door_key(before.doors[0]) == door_key(after.doors[0])
    svg = render_fogged(after, {"room.a"}, {"vault"})
    assert 'class="door-instance"' in svg  # still discovered after the move


def test_duplicate_door_names_warn() -> None:
    d = parse(TWO_ROOMS + 'door "x" at 10,4 { connects room.a, room.b }\n'
              'door "x" at 10,8 { connects room.a, room.b }')
    assert any("door 'x'" in m.message for m in validate(d) if m.severity == "warning")


# ---- between ----

def test_between_two_rooms_sits_on_their_shared_wall() -> None:
    d = parse(TWO_ROOMS + "door between room.a and room.b { type wooden }")
    door = d.doors[0]
    assert door.position == (10.0, 6.0)  # middle of the shared wall x=10, y 2..10
    assert door.connects == ["room.a", "room.b"]


def test_between_a_room_and_a_corridor_sits_where_the_corridor_meets_it() -> None:
    d = parse(HEAD + 'room "a" { rect 2,2 8 x 8 }\n'
              'corridor "k" { width 2 segment line from 10,5 to 20,5 }\n'
              "door between room.a and corridor.k {}")
    assert d.doors[0].position == (10.0, 5.0)


def test_between_finds_a_corridor_that_stops_short_of_the_wall() -> None:
    d = parse(HEAD + 'room "a" { rect 2,2 8 x 8 }\n'
              'corridor "k" { width 2 segment line from 10.4,5 to 20,5 }\n'
              "door between corridor.k and room.a {}")
    assert d.doors[0].position == (10.0, 5.0)
    assert d.doors[0].connects == ["corridor.k", "room.a"]  # order as written


def test_between_two_corridors_meeting_end_to_end() -> None:
    d = parse(HEAD + 'corridor "a" { segment line from 1,5 to 5,5 }\n'
              'corridor "b" { segment line from 5,5 to 9,5 }\n'
              "door between corridor.a and corridor.b { type open }")
    assert d.doors[0].position == (5.0, 5.0)


def test_between_a_corridor_and_another_corridors_side() -> None:
    d = parse(HEAD + 'corridor "a" { width 2 segment line from 2,10 to 30,10 }\n'
                     'corridor "b" { width 2 segment line from 16,2 to 16,9 }\n'
                     "door between corridor.b and corridor.a {}")
    assert d.doors[0].position == (16.0, 9.0)


def test_between_can_be_named_and_moves_with_the_rooms() -> None:
    d = parse(HEAD + 'room "a" { rect 2,12 8 x 8 }\nroom "b" { rect 10,12 8 x 8 }\n'
              'door "arch" between room.a and room.b { type arch }')
    assert d.doors[0].id == "arch" and d.doors[0].position == (10.0, 16.0)


def test_between_in_a_layer_resolves_against_every_scope() -> None:
    d = parse(TWO_ROOMS + 'layer "gm" hidden { door between room.a and room.b { type secret } }')
    assert d.layers[0].doors[0].position == (10.0, 6.0)


def test_between_unknown_node_is_a_parse_error_with_its_line() -> None:
    with pytest.raises(DmapParseError, match="room.nowhere") as ei:
        parse(TWO_ROOMS + "door between room.a and room.nowhere {}")
    assert ei.value.line == 4


def test_between_spaces_that_do_not_touch_is_a_parse_error() -> None:
    with pytest.raises(DmapParseError, match="don't meet"):
        parse(HEAD + 'room "a" { rect 2,2 4 x 4 }\nroom "b" { rect 20,2 4 x 4 }\n'
              "door between room.a and room.b {}")
