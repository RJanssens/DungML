"""Every authored entity carries its source line, wherever it is nested —
the editor places diagnostics by it."""
from __future__ import annotations

from dungml import parse

SRC = """map "M" { grid { bounds 40 x 20 } }
room "top" {
  rect 1,1 5 x 5
  feature pillar at 2,2
  area "pool" kind water { rect 2,2 1 x 1 }
}
layer "L" {
  room "inner" {
    rect 10,1 5 x 5
    feature pillar at 11,2
  }
  corridor "k" { segment line from 6,3 to 10,3 }
  door at 6,3 { connects room.top, corridor.k }
  window at 12,1 { in room.inner }
  marker "orc" at 12,3
  feature pillar at 13,4
  area "puddle" kind mud { rect 12,4 1 x 1 }
  text "hi" at 13,2
  line_feature "rail" { point 11,5 point 13,5 }
  exit at 14,4 { to "other" at 1,1 }
  slice "crack" { kind split segment line from 1,8 to 9,8 }
}
marker "gob" at 3,3
slice "river" { segment line from 1,12 to 30,12 }
line_feature "fence" { point 1,15 point 9,15 }
"""


def test_nested_and_layer_entities_have_source_lines() -> None:
    m = parse(SRC)
    top = m.rooms["top"]
    layer = m.layers[0]
    inner = layer.rooms[0]
    lines = {
        "room top": top.span.line,
        "nested feature": top.features[0].span.line,
        "nested area": top.areas[0].span.line,
        "layer": layer.span.line,
        "layer room": inner.span.line,
        "layer room feature": inner.features[0].span.line,
        "layer corridor": layer.corridors[0].span.line,
        "layer door": layer.doors[0].span.line,
        "layer window": layer.windows[0].span.line,
        "layer marker": layer.markers[0].span.line,
        "layer feature": layer.features[0].span.line,
        "layer area": layer.areas[0].span.line,
        "layer text": layer.texts[0].span.line,
        "layer line_feature": layer.line_features[0].span.line,
        "layer exit": layer.exits[0].span.line,
        "layer slice": layer.slices[0].span.line,
        "marker": m.markers[0].span.line,
        "slice": m.slices["river"].span.line,
        "line_feature": m.line_features[0].span.line,
    }
    assert lines == {
        "room top": 2,
        "nested feature": 4,
        "nested area": 5,
        "layer": 7,
        "layer room": 8,
        "layer room feature": 10,
        "layer corridor": 12,
        "layer door": 13,
        "layer window": 14,
        "layer marker": 15,
        "layer feature": 16,
        "layer area": 17,
        "layer text": 18,
        "layer line_feature": 19,
        "layer exit": 20,
        "layer slice": 21,
        "marker": 23,
        "slice": 24,
        "line_feature": 25,
    }


def test_same_position_doors_get_their_own_spans() -> None:
    m = parse(
        'map "M" { grid { bounds 20 x 20 } }\n'
        'door at 5,5 { type iron }\n'
        'door at 5,5 { type stone }\n'
    )
    assert [d.span.line for d in m.doors] == [2, 3]
