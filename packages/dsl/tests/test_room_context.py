"""room_context: what a room is, split by who may know it."""
from __future__ import annotations

from dungml import build_graph, parse
from dungml.room_context import (
    SessionView, candidates, known_map, node_label, resolve_node, room_context,
)

SRC = '''
map "M" { grid { bounds 40 x 30 } }
feature_def "pit" { shape circle radius 0.5 secret }

room "hall" {
  rect 0,0 10 x 10
  label "39"
  description "A vaulted hall."
  dm_notes "Ghouls sleep under the floor."
  feature altar at 5,5 { description "A cracked altar." }
  feature pillar at 2,2
  feature pillar at 8,2
  feature pit at 3,7
  feature statue at 7,7 { description "A veiled woman." secret }
}
room "cave_2" { rect 20,0 6 x 6  label "37" }
room "cpt_1"  { rect 0,20 4 x 4  label "Cpt" }
room "cpt_2"  { rect 10,20 4 x 4 label "Cpt" }
room "big" { rect 30,10 10 x 10 allow_overlap }
room "nook" { rect 32,12 2 x 2 allow_overlap label "N" }
corridor "c1" "Long Walk" { width 1 segment line from 10,5 to 20,3 }

door at 10,5 { connects room.hall, corridor.c1  type wooden state closed  trapped }
door at 20,3 { connects corridor.c1, room.cave_2  type iron  state locked }
door at 5,10 { connects room.hall, room.cpt_1  type secret }
door at 0,5  { connects room.hall  type arch }

text "F" at 33,13
exit at 6,1 { to "Level 2" at 3,3  label "stairs down" }
exit at 9,9 { to "Vault" at 1,1  secret }
'''


def _setup():
    d = parse(SRC)
    return d, build_graph(d)


def test_resolve_by_id_bare_name_label_and_display_name():
    d, g = _setup()
    assert resolve_node(d, g, "room.hall") == "room.hall"
    assert resolve_node(d, g, "hall") == "room.hall"
    assert resolve_node(d, g, "39") == "room.hall"
    assert resolve_node(d, g, "long walk") == "corridor.c1"
    assert resolve_node(d, g, "nowhere") is None


def test_shared_label_is_ambiguous_and_lists_candidates():
    d, g = _setup()
    assert resolve_node(d, g, "Cpt") is None
    ids = sorted(c["id"] for c in candidates(d, g, "Cpt"))
    assert ids == ["room.cpt_1", "room.cpt_2"]


def test_perceived_carries_boxed_text_and_visible_exits():
    d, g = _setup()
    ctx = room_context(d, g, "room.hall", SessionView(discovered_doors=frozenset({"10,5", "0,5"})))
    assert ctx["label"] == "39"
    p = ctx["perceived"]
    assert p["description"] == "A vaulted hall."
    by_door = {e["door"]: e for e in p["exits"]}
    assert by_door["10,5"]["to"] == "corridor.c1"
    # The corridor beyond hasn't been entered: its name is DM-side only.
    assert by_door["10,5"]["to_label"] is None
    assert ctx["dm_only"]["exit_labels"]["10,5"] == "Long Walk"
    assert by_door["10,5"]["state"] == "closed"
    assert by_door["0,5"]["to"] is None            # boundary opening
    assert "5,10" not in by_door                    # secret, unfound


def test_unexplored_exit_label_is_dm_only():
    d, g = _setup()
    ctx = room_context(d, g, "room.hall", SessionView(discovered_doors=frozenset({"10,5", "0,5"})))
    by_door = {e["door"]: e for e in ctx["perceived"]["exits"]}
    assert by_door["10,5"]["far_side_explored"] is False
    assert by_door["10,5"]["to_label"] is None
    assert by_door["10,5"]["to"] == "corridor.c1"      # still usable to move/reveal
    assert "Long Walk" not in str(ctx["perceived"])
    assert ctx["dm_only"]["exit_labels"] == {"10,5": "Long Walk"}


def test_explored_exit_keeps_its_label():
    d, g = _setup()
    view = SessionView(discovered_nodes=frozenset({"room.hall", "corridor.c1"}),
                       discovered_doors=frozenset({"10,5"}))
    ctx = room_context(d, g, "room.hall", view)
    by_door = {e["door"]: e for e in ctx["perceived"]["exits"]}
    assert by_door["10,5"]["to_label"] == "Long Walk"
    assert "10,5" not in ctx["dm_only"]["exit_labels"]


def test_dm_only_holds_notes_secrets_and_traps():
    d, g = _setup()
    ctx = room_context(d, g, "room.hall", SessionView())
    dm = ctx["dm_only"]
    assert dm["notes"] == "Ghouls sleep under the floor."
    assert [s["door"] for s in dm["secret_exits"]] == ["5,10"]
    assert dm["secret_exits"][0]["to_label"] == "Cpt"
    assert dm["trapped_doors"] == ["10,5"]
    secret_names = sorted(f["name"] for f in dm["secret_features"])
    assert secret_names == ["pit", "statue"]
    assert "trapped" not in str(ctx["perceived"])
    assert "veiled" not in str(ctx["perceived"])
    assert "Ghouls" not in str(ctx["perceived"])


def test_found_secret_door_moves_to_perceived():
    d, g = _setup()
    ctx = room_context(d, g, "room.hall", SessionView(discovered_doors=frozenset({"5,10"})))
    assert "5,10" in {e["door"] for e in ctx["perceived"]["exits"]}
    assert ctx["dm_only"]["secret_exits"] == []


def test_effective_door_state_uses_session_override():
    d, g = _setup()
    view = SessionView(discovered_doors=frozenset({"20,3"}), door_states={"20,3": "open"})
    ctx = room_context(d, g, "room.cave_2", view)
    e = next(x for x in ctx["perceived"]["exits"] if x["door"] == "20,3")
    assert e["state"] == "open" and e["blocked"] is False


def test_undiscovered_visible_doors_are_listed_for_the_dm():
    d, g = _setup()
    ctx = room_context(d, g, "room.hall", SessionView())
    assert sorted(e["door"] for e in ctx["dm_only"]["undiscovered_exits"]) == ["0,5", "10,5"]


def test_plain_features_are_counted_and_described_ones_listed():
    d, g = _setup()
    feats = room_context(d, g, "room.hall", SessionView())["perceived"]["features"]
    assert {"name": "altar", "description": "A cracked altar."} in feats
    assert {"name": "pillar", "count": 2} in feats


def test_map_level_text_and_exits_belong_to_the_smallest_containing_node():
    d, g = _setup()
    nook = room_context(d, g, "room.nook", SessionView())
    big = room_context(d, g, "room.big", SessionView())
    assert [a["text"] for a in nook["perceived"]["annotations"]] == ["F"]
    assert big["perceived"]["annotations"] == []
    hall = room_context(d, g, "room.hall", SessionView())
    assert [x["target_map"] for x in hall["perceived"]["map_exits"]] == ["Level 2"]
    assert [x["target_map"] for x in hall["dm_only"]["secret_map_exits"]] == ["Vault"]


def test_flags_discovered_and_party_here():
    d, g = _setup()
    ctx = room_context(d, g, "room.hall",
                       SessionView(discovered_nodes=frozenset({"room.hall"}), party_location="room.hall"))
    assert ctx["discovered"] is True and ctx["party_here"] is True


def test_known_map_labels_connections_and_frontier():
    d, g = _setup()
    view = SessionView(discovered_nodes=frozenset({"room.hall", "corridor.c1"}),
                       discovered_doors=frozenset({"10,5", "20,3"}), party_location="corridor.c1")
    km = known_map(d, g, view)
    assert km["party_location"] == "corridor.c1"
    assert {"id": "room.hall", "kind": "room", "label": "39"} in km["nodes"]
    assert [c["door"] for c in km["connections"]] == ["10,5"]
    assert km["frontier"][0]["leads_to"] == "room.cave_2"
    assert km["frontier"][0]["leads_to_label"] == "37"


def test_node_label_falls_back_to_bare_name():
    d, _ = _setup()
    assert node_label(d, "room.big") == "big"


# ----- fix round 1: colliding door keys, hidden layers, one-way doors -----

SRC_COLLIDING_DOORS = '''
map "M" { grid { bounds 20 x 20 } }
room "a" { rect 0,0 6 x 6 }
room "b" { rect 10,0 6 x 6 }
room "c" { rect 0,10 6 x 6 }
door at 6,3 { connects room.a, room.c  type secret  state closed  trapped
              description "Behind the tapestry, a secret passage." }
door at 6,3 { connects room.a, room.b  type wooden  state closed }
'''


def test_colliding_door_keys_do_not_cross_attach_extras():
    d = parse(SRC_COLLIDING_DOORS)
    g = build_graph(d)
    # Discover both doors so the leak (or its absence) shows up in one place:
    # `perceived["exits"]`, where a leaked secret description would be most
    # damaging (Hard Constraint #5 — DM-only text bleeding to the player).
    keys = {e.key for e in g.incident_edges("room.a")}
    view = SessionView(discovered_doors=frozenset(keys))
    ctx = room_context(d, g, "room.a", view)
    assert ctx["dm_only"]["secret_exits"] == []
    assert len(ctx["perceived"]["exits"]) == 2
    secret = next(e for e in ctx["perceived"]["exits"] if e["to"] == "room.c")
    plain = next(e for e in ctx["perceived"]["exits"] if e["to"] == "room.b")
    assert secret["door"] != plain["door"]
    # The plain wooden door must not inherit the secret door's description.
    assert "description" not in plain
    assert secret["description"] == "Behind the tapestry, a secret passage."
    # Only the secret door is actually trapped.
    assert ctx["dm_only"]["trapped_doors"] == [secret["door"]]


SRC_HIDDEN_LAYER = '''
map "M" { grid { bounds 20 x 20 } }
room "hall" { rect 0,0 10 x 10 }
layer "gm" hidden {
  text "PIT TRAP HERE" at 5,5
  exit at 3,3 { to "Secret Level" at 1,1 }
}
'''


def test_hidden_layer_texts_and_exits_never_reach_perceived():
    d = parse(SRC_HIDDEN_LAYER)
    g = build_graph(d)
    ctx = room_context(d, g, "room.hall", SessionView())
    assert ctx["perceived"]["annotations"] == []
    assert ctx["perceived"]["map_exits"] == []
    assert {"text": "PIT TRAP HERE", "hidden_layer": True} in ctx["dm_only"]["hidden_annotations"]
    assert [x["target_map"] for x in ctx["dm_only"]["secret_map_exits"]] == ["Secret Level"]


SRC_ONE_WAY = '''
map "M" { grid { bounds 20 x 20 } }
room "a" { rect 0,0 6 x 6 }
room "b" { rect 10,0 6 x 6 }
door at 6,3 { connects room.a, room.b  type oneway  state closed }
'''


def test_one_way_door_appears_on_the_far_side_as_blocked():
    d = parse(SRC_ONE_WAY)
    g = build_graph(d)
    # sanity: build_graph only adds the edge to the forward side's adjacency
    assert g.incident_edges("room.b") == []
    ctx = room_context(d, g, "room.b", SessionView())
    exits = ctx["perceived"]["exits"] + ctx["dm_only"]["undiscovered_exits"]
    entry = next(e for e in exits if e["to"] == "room.a")
    assert entry["blocked"] is True
    assert entry["one_way"] is True
    # The forward side still sees a normal, unblocked exit.
    fwd_ctx = room_context(d, g, "room.a", SessionView())
    fwd_exits = fwd_ctx["perceived"]["exits"] + fwd_ctx["dm_only"]["undiscovered_exits"]
    fwd_entry = next(e for e in fwd_exits if e["to"] == "room.b")
    assert fwd_entry["blocked"] is False
