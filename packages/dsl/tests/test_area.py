"""Top-level `area` terrain primitive: parser, model, renderer, validation."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from dungml import Area, parse, render
from dungml.validate import validate

SVG_NS = "{http://www.w3.org/2000/svg}"


def _parse_svg(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def _areas(root: ET.Element) -> list[ET.Element]:
    return [e for e in root.iter() if e.get("class") == "area"]


def test_area_parses_kind_before_brace() -> None:
    src = """
    map "X" { grid { bounds 30 x 30 } }
    area "pond" kind water { polygon (1,1) (5,1) (5,5) (1,5) }
    """
    m = parse(src)
    assert len(m.areas) == 1
    a = m.areas[0]
    assert isinstance(a, Area)
    assert a.name == "pond"
    assert a.kind == "water"
    assert a.shape.kind == "polygon"


def test_area_parses_kind_inside_block_and_modifiers() -> None:
    src = """
    map "X" { grid { bounds 30 x 30 } }
    area "lake" {
      kind water
      polygon (1,1) (8,1) (8,8) (1,8)
      line_style organic
      label "Black Lake"
    }
    """
    a = parse(src).areas[0]
    assert a.kind == "water"
    assert a.line_style == "organic"
    assert a.label is not None and a.label.text == "Black Lake"


def test_area_defaults_to_water_kind() -> None:
    src = """
    map "X" { grid { bounds 30 x 30 } }
    area "p" { rect 1,1 3 x 3 }
    """
    assert parse(src).areas[0].kind == "water"


def test_area_renders_filled_path_with_kind_data() -> None:
    src = """
    map "X" { grid { cell 20 px bounds 30 x 30 } renderer "classic-bw" }
    area "lava" kind lava { polygon (1,1) (8,1) (8,8) (1,8) }
    """
    root = _parse_svg(render(parse(src)))
    areas = _areas(root)
    assert len(areas) == 1
    el = areas[0]
    assert el.get("data-kind") == "lava"
    assert "fill:#e2521d" in (el.get("style") or "")


def test_water_kind_registers_texture_pattern() -> None:
    # The water texture comes from the kind palette (not an explicit
    # `background`), so it must still be registered in <defs> up front.
    src = """
    map "X" { grid { cell 20 px bounds 30 x 30 } renderer "classic-bw" }
    area "pond" kind water { polygon (1,1) (8,1) (8,8) (1,8) }
    """
    svg = render(parse(src))
    assert 'pattern id="dungml-tx-water"' in svg
    assert "fill:url(#dungml-tx-water)" in svg


def test_area_in_layer_renders() -> None:
    src = """
    map "X" { grid { cell 20 px bounds 30 x 30 } renderer "classic-bw" }
    layer "hazards" { area "pit" kind pit { rect 2,2 4 x 4 } }
    """
    m = parse(src)
    assert len(m.layers[0].areas) == 1
    assert len(_areas(_parse_svg(render(m)))) == 1


def test_area_is_not_a_room() -> None:
    # Areas must not leak into the room collection / graph.
    src = """
    map "X" { grid { bounds 30 x 30 } }
    area "pond" kind water { polygon (1,1) (5,1) (5,5) }
    """
    m = parse(src)
    assert "pond" not in m.rooms


def test_unknown_kind_warns_but_renders() -> None:
    src = """
    map "X" { grid { cell 20 px bounds 30 x 30 } renderer "classic-bw" }
    area "x" kind watr { rect 1,1 3 x 3 }
    """
    m = parse(src)
    diags = validate(m)
    assert any(d.severity == "warning" and "unknown kind" in d.message for d in diags)
    # still renders (neutral fallback)
    assert len(_areas(_parse_svg(render(m)))) == 1


def test_area_polygon_too_few_points_errors() -> None:
    src = """
    map "X" { grid { bounds 30 x 30 } }
    area "bad" kind water { polygon (1,1) (5,5) }
    """
    diags = validate(parse(src))
    assert any(d.severity == "error" and "at least 3" in d.message for d in diags)
