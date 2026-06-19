"""Tests for the connectivity graph + pathfinding (`dungml.graph`)."""
from __future__ import annotations

from dungml import (
    build_graph,
    door_key,
    fog_of_war,
    is_blocked,
    parse,
)
from dungml.graph import Edge

# Three rooms in a line:
#   antechamber --(door open)-- passage(corridor) --(door locked)-- sanctum
#   sanctum --(open door)-- vault
# plus a one-sided secret door on the antechamber (boundary exit).
SRC = """
map "Test" {
  grid { bounds 60 x 40 }
}

room "antechamber" { rect 2,4 12 x 10 label "Ante" }
room "sanctum"     { rect 18,4 10 x 10 label "Sanctum" }
room "vault"       { rect 30,4 8 x 8 label "Vault" }

corridor "passage" { width 2 segment line from 14,9 to 18,9 }

door at 14,9 { connects room.antechamber, corridor.passage }
door at 18,9 { connects room.sanctum, corridor.passage  state locked  type iron }
door at 28,7 { connects room.sanctum, room.vault }
door at 8,14 { connects room.antechamber  type secret }
"""


def _graph():
    return build_graph(parse(SRC))


def test_nodes_include_rooms_and_corridors():
    g = _graph()
    assert set(g.nodes) == {
        "room.antechamber",
        "room.sanctum",
        "room.vault",
        "corridor.passage",
    }
    assert g.nodes["corridor.passage"].kind == "corridor"
    assert g.nodes["room.vault"].kind == "room"


def test_edges_from_doors():
    g = _graph()
    pairs = {frozenset((e.a, e.b)) for e in g.edges}
    assert frozenset(("room.antechamber", "corridor.passage")) in pairs
    assert frozenset(("room.sanctum", "corridor.passage")) in pairs
    assert frozenset(("room.sanctum", "room.vault")) in pairs


def test_single_connect_door_is_boundary_exit():
    g = _graph()
    assert len(g.boundary) == 1
    b = g.boundary[0]
    assert b.node == "room.antechamber"
    assert b.hidden is True  # secret type


def test_door_key_is_compact():
    g = _graph()
    keys = {e.key for e in g.edges}
    assert "14,9" in keys
    assert "28,7" in keys


def test_neighbors():
    g = _graph()
    neigh = {n for n, _ in g.neighbors("corridor.passage")}
    assert neigh == {"room.antechamber", "room.sanctum"}


def test_find_path_any_mode_traverses_locked_door():
    g = _graph()
    # No passable gate => locked door is fine (DM "does a route exist?").
    path = g.find_path("room.antechamber", "room.vault")
    assert path is not None
    assert path.nodes == [
        "room.antechamber",
        "corridor.passage",
        "room.sanctum",
        "room.vault",
    ]
    assert path.length == 3


def test_find_path_respects_passable_gate():
    g = _graph()
    # Block locked doors: antechamber can no longer reach sanctum/vault.
    passable = lambda e: not is_blocked(e.state)
    assert g.find_path("room.antechamber", "room.vault", passable=passable) is None
    # ...but the locked door's near side is still reachable trivially.
    near = g.find_path("room.antechamber", "corridor.passage", passable=passable)
    assert near is not None and near.length == 1


def test_find_path_respects_node_gate():
    g = _graph()
    discovered = {"room.antechamber", "corridor.passage"}
    node_ok = lambda n: n in discovered
    assert g.find_path("room.antechamber", "room.sanctum", node_ok=node_ok) is None
    ok = g.find_path("room.antechamber", "corridor.passage", node_ok=node_ok)
    assert ok is not None


def test_find_path_same_node_is_trivial():
    g = _graph()
    p = g.find_path("room.vault", "room.vault")
    assert p is not None and p.nodes == ["room.vault"] and p.length == 0


def test_find_path_unknown_node_returns_none():
    g = _graph()
    assert g.find_path("room.nope", "room.vault") is None


def test_path_to_dict_shape():
    g = _graph()
    d = g.find_path("room.sanctum", "room.vault").to_dict()
    assert d["found"] is True
    assert d["doors"] == ["28,7"]
    assert d["steps"][0]["from"] == "room.sanctum"
    assert d["steps"][0]["to"] == "room.vault"


def test_fog_of_war_prunes_undiscovered():
    dmap = parse(SRC)
    fogged = fog_of_war(
        dmap,
        discovered_nodes={"room.antechamber", "corridor.passage"},
        discovered_doors={"14,9"},
    )
    assert set(fogged.rooms) == {"antechamber"}
    assert set(fogged.corridors) == {"passage"}
    # only the discovered door survives
    assert [door_key(d) for d in fogged.doors] == ["14,9"]
    # the original is untouched (deep copy)
    assert set(dmap.rooms) == {"antechamber", "sanctum", "vault"}


def test_position_collision_disambiguated():
    src = """
    map "C" { grid { bounds 20 x 20 } }
    room "a" { rect 1,1 4 x 4 }
    room "b" { rect 6,1 4 x 4 }
    door at 5,3 { connects room.a, room.b }
    door at 5,3 { connects room.a, room.b }
    """
    g = build_graph(parse(src))
    keys = [e.key for e in g.edges]
    assert keys[0] == "5,3"
    assert keys[1] == "5,3#2"
