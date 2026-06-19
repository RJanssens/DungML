"""Top-level `text` annotation: parser, model, renderer, validation."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from dungml import TextAnnotation, parse, render
from dungml.validate import validate

SVG_NS = "{http://www.w3.org/2000/svg}"


def _parse_svg(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def test_text_parses_required_fields() -> None:
    src = """
    map "X" { grid { bounds 20 x 20 } }
    text "Hello" at 5,6
    """
    m = parse(src)
    assert len(m.texts) == 1
    t = m.texts[0]
    assert isinstance(t, TextAnnotation)
    assert t.text == "Hello"
    assert t.position == (5.0, 6.0)
    assert t.size == 1.0
    assert t.rotate == 0.0


def test_text_parses_modifiers() -> None:
    src = """
    map "X" { grid { bounds 20 x 20 } }
    text "Grand Hall" at 5,6 size 2.5 rotate 30
        description "carved over the arch"
    """
    t = parse(src).texts[0]
    assert t.size == 2.5
    assert t.rotate == 30.0
    assert t.description == "carved over the arch"


def test_text_renders_svg_text_element() -> None:
    src = """
    map "X" { grid { cell 20 px bounds 20 x 20 } renderer "classic-bw" }
    text "Big Sign" at 5,6 size 2
    """
    root = _parse_svg(render(parse(src)))
    texts = [
        e
        for e in root.iter(f"{SVG_NS}text")
        if "text-annotation" in (e.get("class") or "")
    ]
    assert len(texts) == 1
    el = texts[0]
    assert el.text == "Big Sign"
    # size 2 * LABEL_BASE_SIZE (0.9) == 1.8
    assert el.get("font-size") == "1.8"
    assert el.get("text-anchor") == "middle"
    assert "translate(5,6)" in el.get("transform")


def test_text_in_layer_renders() -> None:
    src = """
    map "X" { grid { cell 20 px bounds 20 x 20 } renderer "classic-bw" }
    layer "notes" {
      text "layer note" at 3,3
    }
    """
    m = parse(src)
    assert len(m.layers[0].texts) == 1
    root = _parse_svg(render(m))
    texts = [
        e
        for e in root.iter(f"{SVG_NS}text")
        if "text-annotation" in (e.get("class") or "")
    ]
    assert [e.text for e in texts] == ["layer note"]


def test_text_escapes_markup() -> None:
    src = """
    map "X" { grid { cell 20 px bounds 20 x 20 } renderer "classic-bw" }
    text "a < b & c" at 5,6
    """
    svg = render(parse(src))
    assert "a < b & c" not in svg  # raw markup must be escaped
    root = _parse_svg(svg)  # must still be well-formed XML
    texts = [
        e
        for e in root.iter(f"{SVG_NS}text")
        if "text-annotation" in (e.get("class") or "")
    ]
    assert texts[0].text == "a < b & c"


def test_text_out_of_bounds_warns() -> None:
    src = """
    map "X" { grid { bounds 20 x 20 } }
    text "off the edge" at 50,50
    """
    diags = validate(parse(src))
    assert any(
        d.severity == "warning" and "off the edge" in d.message for d in diags
    )


def test_text_non_positive_size_errors() -> None:
    src = """
    map "X" { grid { bounds 20 x 20 } }
    text "bad" at 5,5 size 0
    """
    diags = validate(parse(src))
    assert any(d.severity == "error" and "non-positive" in d.message for d in diags)
