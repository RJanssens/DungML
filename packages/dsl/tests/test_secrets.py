"""GM-only content the DM can reveal.

`secret` marks anything the players shouldn't see until the DM shows it —
a trap (feature types can be secret by default, as core.dmap's traps are),
a hidden inscription, a pit, a lurking marker, a concealed exit. The players'
view hides it; a play session's reveal list brings it back, keyed by the
entity's `id` if it has one, else by where it sits.

Hidden layers are a different thing: wholly GM-only, never drawn for the
players, so nothing in them is revealable.
"""
from __future__ import annotations

import re

from dungml import build_graph, fog_of_war, parse, render_fogged, validate
from dungml.room_context import SessionView, room_context
from dungml.secrets import list_secrets

SRC = """include "core.dmap"
map "M" { grid { bounds 40 x 20 } }
room "crypt" {
  rect 1,1 10 x 10
  label "Crypt"
  feature pit-trap at 3,3
  feature pillar at 5,5 id plinth { secret description "A loose plinth." }
  feature pillar at 7,7
  text "Beware" at 4,8 secret
  area "sinkhole" kind pit { rect 8,2 1 x 1 secret }
  exit at 9,9 { to "below" at 1,1 secret }
}
room "hall" { rect 12,1 6 x 6 label "Hall" }
door at 11,4 { connects room.crypt, room.hall }
marker "lurker" at 14,3 secret
line_feature "tripwire" kind bars { point 13,5 point 16,5 secret }
exit at 17,6 { to "roof" at 1,1 id skylight secret }
layer "gm" hidden { feature pit-trap at 15,5 }
"""

NODES = {"room.crypt", "room.hall"}
DOORS = {"11,4"}


def _keys(dmap) -> dict[str, str]:
    return {s.key: s.kind for s in list_secrets(dmap)}


def test_every_kind_of_secret_is_listed_with_a_stable_key() -> None:
    assert _keys(parse(SRC)) == {
        "room.crypt/feature@3,3": "feature",  # pit-trap: secret by type
        "plinth": "feature",  # explicit id wins
        "room.crypt/text@4,8": "text",
        "room.crypt/area:sinkhole": "area",
        "room.crypt/exit@9,9": "exit",
        "map/marker:lurker": "marker",
        "map/line:tripwire": "line_feature",
        "skylight": "exit",
    }


def test_secrets_know_which_node_they_are_in() -> None:
    nodes = {s.key: s.node for s in list_secrets(parse(SRC))}
    assert nodes["plinth"] == "room.crypt"
    assert nodes["map/marker:lurker"] == "room.hall"  # by position
    assert nodes["skylight"] == "room.hall"


def test_hidden_layer_content_is_not_revealable() -> None:
    assert not any("gm" in k or "15,5" in k for k in _keys(parse(SRC)))


def _refs(svg: str) -> list[str]:
    return re.findall(r'data-ref="([^"]+)"', svg)


def test_players_view_hides_every_unrevealed_secret() -> None:
    svg = render_fogged(parse(SRC), NODES, DOORS)
    assert _refs(svg) == ["pillar"]  # only the plain pillar at 7,7
    assert "Beware" not in svg
    assert 'data-area="sinkhole"' not in svg
    assert 'data-name="lurker"' not in svg
    assert 'data-line-feature="tripwire"' not in svg
    assert 'data-exit-to' not in svg


def test_revealed_secrets_come_back_one_by_one() -> None:
    svg = render_fogged(
        parse(SRC), NODES, DOORS,
        revealed={"room.crypt/feature@3,3", "plinth", "map/marker:lurker", "skylight"},
    )
    assert sorted(_refs(svg)) == ["pillar", "pillar", "pit-trap"]
    assert 'data-name="lurker"' in svg
    assert 'data-exit-to="roof"' in svg
    assert "Beware" not in svg  # not revealed
    assert 'data-exit-to="below"' not in svg


def test_revealing_does_not_leak_dm_notes() -> None:
    src = SRC.replace('id plinth { secret description "A loose plinth." }',
                      'id plinth { secret dm_notes "PLINTH-NOTE" }')
    fogged = fog_of_war(parse(src), NODES, DOORS, revealed={"plinth"})
    assert "PLINTH-NOTE" not in fogged.model_dump_json()


def test_room_context_lists_the_rooms_secrets_for_the_dm() -> None:
    dmap = parse(SRC)
    g = build_graph(dmap)
    view = SessionView(discovered_nodes=frozenset(NODES), revealed=frozenset({"plinth"}))
    ctx = room_context(dmap, g, "room.crypt", view)
    listed = {s["key"]: s["revealed"] for s in ctx["dm_only"]["secrets"]}
    assert listed == {
        "room.crypt/feature@3,3": False,
        "plinth": True,
        "room.crypt/text@4,8": False,
        "room.crypt/area:sinkhole": False,
        "room.crypt/exit@9,9": False,
    }
    # A revealed secret is part of what the party perceives.
    assert {"name": "pillar", "description": "A loose plinth."} in ctx["perceived"]["features"]
    secret_names = {f.get("key") for f in ctx["dm_only"]["secret_features"]}
    assert secret_names == {"room.crypt/feature@3,3", "plinth"}


def test_duplicate_secret_keys_warn() -> None:
    src = SRC.replace("feature pillar at 7,7", "feature pillar at 7,7 id plinth { secret }")
    warns = [d.message for d in validate(parse(src)) if d.severity == "warning"]
    assert any("secret key 'plinth'" in m for m in warns), warns


def test_a_secret_in_a_hidden_layer_room_stays_dm_only() -> None:
    # Not revealable (no key), but still secret: never "perceived".
    src = SRC.replace('layer "gm" hidden { feature pit-trap at 15,5 }',
                      'layer "gm" hidden { room "vault" { rect 30,1 5 x 5 feature pit-trap at 32,3 } }')
    dmap = parse(src)
    ctx = room_context(dmap, build_graph(dmap), "room.vault",
                       SessionView(discovered_nodes=frozenset({"room.vault"})))
    assert ctx["perceived"]["features"] == []
    assert ctx["dm_only"]["secret_features"] == [{"name": "pit-trap", "revealed": False}]
    assert ctx["dm_only"]["secrets"] == []
