"""Marker top-level construct: parser, model, palette, renderer."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from dungml import Marker, parse, render
from dungml.render.classic_bw import MARKER_PALETTE

SVG_NS = "{http://www.w3.org/2000/svg}"


def _parse_svg(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def test_marker_parses_required_fields() -> None:
    src = """
    map "X" { grid { bounds 20 x 20 } }
    room "r" { rect 1,1 10 x 10 }
    marker "Aragorn" at 5,5 tag party
    """
    m = parse(src)
    assert len(m.markers) == 1
    mk = m.markers[0]
    assert isinstance(mk, Marker)
    assert mk.name == "Aragorn"
    assert mk.position == (5.0, 5.0)
    assert mk.tag == "party"


def test_marker_supports_all_modifiers() -> None:
    src = """
    map "X" { grid { bounds 20 x 20 } }
    room "r" { rect 1,1 10 x 10 }
    marker "Old Pelmar" at 5,5
        tag npc
        label "Old Pelmar (sage)"
        initial "P"
        size 0.7
        in room.r
        description "Half-blind, sharp-witted."
        dm_notes "Holds the key to the south corridor."
    """
    mk = parse(src).markers[0]
    assert mk.label == "Old Pelmar (sage)"
    assert mk.initial == "P"
    assert mk.size == 0.7
    assert mk.location == "room.r"
    assert mk.description == "Half-blind, sharp-witted."
    assert mk.dm_notes == "Holds the key to the south corridor."


def test_marker_tag_accepts_hex_literal() -> None:
    src = '''
    map "X" { grid { bounds 20 x 20 } }
    room "r" { rect 1,1 5 x 5 }
    marker "Custom" at 3,3 tag "#ff8800"
    '''
    mk = parse(src).markers[0]
    assert mk.tag == "#ff8800"


def test_marker_inside_hidden_layer_collected_but_not_rendered() -> None:
    src = """
    map "X" { grid { bounds 20 x 20 } }
    room "r" { rect 1,1 10 x 10 }
    layer "secrets" hidden {
      marker "Invisible Stalker" at 5,5 tag unknown
    }
    """
    m = parse(src)
    # Model still carries the marker inside the hidden layer.
    assert m.layers[0].hidden is True
    assert len(m.layers[0].markers) == 1
    # Renderer skips hidden layers, so no marker group appears.
    svg = render(m)
    root = _parse_svg(svg)
    marker_groups = [
        e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "markers"
    ]
    assert marker_groups == []


def test_renderer_emits_marker_group_with_palette_color() -> None:
    src = """
    map "X" { grid { bounds 30 x 20 } }
    room "main" { rect 1,1 28 x 18 label "Hall" }
    marker "Aragorn"     at 4,4   tag party
    marker "Goblin Boss" at 20,4  tag boss
    marker "Pelmar"      at 12,10 tag npc
    """
    m = parse(src)
    svg = render(m)
    root = _parse_svg(svg)
    groups = [e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "markers"]
    assert len(groups) == 1
    instances = [
        e for e in groups[0].iter(f"{SVG_NS}g") if e.get("class") == "marker"
    ]
    assert len(instances) == 3
    names = {e.get("data-name") for e in instances}
    assert names == {"Aragorn", "Goblin Boss", "Pelmar"}
    # Each marker's circle uses the palette colour for its tag.
    for inst in instances:
        tag = inst.get("data-tag")
        circle = next(inst.iter(f"{SVG_NS}circle"))
        assert circle.get("fill") == MARKER_PALETTE[tag]


def test_renderer_uses_first_letter_when_no_initial_given() -> None:
    src = """
    map "X" { grid { bounds 20 x 20 } }
    room "r" { rect 1,1 5 x 5 }
    marker "Aragorn" at 3,3 tag party
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    marker = next(
        e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "marker"
    )
    text_el = next(marker.iter(f"{SVG_NS}text"))
    assert text_el.text == "A"


def test_renderer_emits_label_caption_when_set() -> None:
    src = """
    map "X" { grid { bounds 20 x 20 } }
    room "r" { rect 1,1 10 x 10 }
    marker "Boss" at 5,5 tag boss label "Broken-Tooth"
    """
    svg = render(parse(src))
    assert "Broken-Tooth" in svg


def test_marker_image_parses() -> None:
    src = '''
    map "X" { grid { bounds 20 x 20 } }
    room "r" { rect 1,1 10 x 10 }
    marker "Aragorn" at 5,5 tag party image "tokens/aragorn.png"
    '''
    mk = parse(src).markers[0]
    assert mk.image == "tokens/aragorn.png"


def test_marker_image_renders_image_element_and_suppresses_initial() -> None:
    src = '''
    map "X" { grid { bounds 20 x 20 } }
    room "r" { rect 1,1 10 x 10 }
    marker "Aragorn" at 5,5 tag party image "https://example.com/aragorn.png"
    '''
    svg = render(parse(src))
    root = _parse_svg(svg)
    marker = next(
        e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "marker"
    )
    image = next(marker.iter(f"{SVG_NS}image"), None)
    assert image is not None
    assert image.get("href") == "https://example.com/aragorn.png"
    # No initial-letter text on an image marker.
    assert next(marker.iter(f"{SVG_NS}text"), None) is None
    # Clip path defined so the image stays inside the circular token.
    clip = next(marker.iter(f"{SVG_NS}clipPath"), None)
    assert clip is not None
    clip_id = clip.get("id")
    assert image.get("clip-path") == f"url(#{clip_id})"


def test_marker_image_keeps_tag_colored_ring_as_border() -> None:
    src = '''
    map "X" { grid { bounds 20 x 20 } }
    room "r" { rect 1,1 10 x 10 }
    marker "Boss" at 5,5 tag boss image "tokens/boss.png"
    '''
    svg = render(parse(src))
    root = _parse_svg(svg)
    marker = next(
        e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "marker"
    )
    # First <circle> outside the clipPath is the colored ring stroke.
    ring = next(
        c for c in marker.iter(f"{SVG_NS}circle")
        if c.get("fill") == "none"
    )
    assert ring.get("stroke") == MARKER_PALETTE["boss"]


def test_marker_with_hex_tag_renders_with_that_color() -> None:
    src = '''
    map "X" { grid { bounds 20 x 20 } }
    room "r" { rect 1,1 10 x 10 }
    marker "Custom" at 5,5 tag "#ff8800"
    '''
    svg = render(parse(src))
    root = _parse_svg(svg)
    marker = next(
        e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "marker"
    )
    circle = next(marker.iter(f"{SVG_NS}circle"))
    assert circle.get("fill") == "#ff8800"
