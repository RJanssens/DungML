"""`dungml.walk` — the one definition of "what is in this map".

Renderer, graph, geometry, fog stubs, room_context and the MCP server all
used to re-derive "top level, then layers, then things nested in rooms and
corridors" by hand, and the copies drifted (areas nested in layer rooms never
rendered; the MCP node map let a layer room override a top-level one while
everything else let the top level win). These tests pin the shared rules.
"""
from __future__ import annotations

from dungml import parse
from dungml.walk import members, nodes

SRC = """
map "M" { grid { bounds 40 x 20 } }
room "a" { rect 1,1 5 x 5  text "ta" at 2,2  area "pa" { rect 2,2 1 x 1 } }
corridor "k" { segment line from 6,3 to 10,3  text "tk" at 7,3 }
text "free-top" at 1,19
feature pillar at 3,3
layer "open" {
  room "b" { rect 10,1 5 x 5  text "tb" at 11,2  feature pillar at 11,3 }
  room "a" { rect 20,1 5 x 5 }
  corridor "k2" { segment line from 15,3 to 20,3 }
  text "free-open" at 2,19
  door at 10,3 { connects corridor.k, room.b }
  slice "crack" { kind split segment line from 1,10 to 9,10 }
}
layer "gm" hidden {
  room "s" { rect 30,1 5 x 5  text "ts" at 31,2  area "ps" { rect 31,2 1 x 1 } }
  text "free-gm" at 3,19
  door at 30,3 { connects room.s }
}
slice "river" { segment line from 1,15 to 30,15 }
"""


def _texts(dmap, **kw) -> list[str]:
    return [p.item.text for p in members(dmap, "texts", **kw)]


def test_nodes_first_definition_wins_top_level_then_layers() -> None:
    d = parse(SRC)
    n = nodes(d)
    # All rooms, then all corridors — the order build_graph has always used.
    assert list(n) == [
        "room.a", "room.b", "room.s", "corridor.k", "corridor.k2",
    ]
    assert n["room.a"].shape.position == (1.0, 1.0)  # not the layer's "a"


def test_visible_skips_hidden_layers() -> None:
    d = parse(SRC)
    assert "room.s" not in nodes(d, visible=True)
    assert [p.item.position for p in members(d, "doors", visible=True)] == [(10.0, 3.0)]
    assert len(members(d, "doors")) == 2


def test_free_then_nested_order_and_hidden_filtering() -> None:
    d = parse(SRC)
    assert _texts(d) == [
        "free-top", "free-open", "free-gm",  # freestanding: top, then layers
        "ta", "tb", "ts",                    # nested in rooms (deduped order)
        "tk",                                 # nested in corridors
    ]
    assert _texts(d, visible=True) == ["free-top", "free-open", "ta", "tb", "tk"]


def test_nested_first_order() -> None:
    d = parse(SRC)
    assert [p.item.position for p in members(d, "features", nested_first=True)] == [
        (11.0, 3.0), (3.0, 3.0),
    ]


def test_placement_records_layer_and_host() -> None:
    d = parse(SRC)
    by_text = {p.item.text: p for p in members(d, "texts")}
    assert by_text["tb"].layer.name == "open" and by_text["tb"].host.name == "b"
    assert by_text["free-open"].layer.name == "open" and by_text["free-open"].host is None
    assert by_text["ta"].layer is None and by_text["ta"].host.name == "a"
    assert by_text["ts"].hidden and not by_text["tb"].hidden
    # A room in a hidden layer makes its nested content hidden too.
    ps = next(p for p in members(d, "areas") if p.item.name == "ps")
    assert ps.hidden


def test_named_kinds_are_deduped_and_slices_span_both_containers() -> None:
    d = parse(SRC)
    assert [p.item.name for p in members(d, "rooms")] == ["a", "b", "s"]
    assert [p.item.name for p in members(d, "slices")] == ["river", "crack"]
