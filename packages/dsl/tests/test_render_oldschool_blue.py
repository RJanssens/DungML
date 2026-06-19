from __future__ import annotations

import xml.etree.ElementTree as ET

from dungml import parse, render
from dungml.render import get_renderer, list_renderers
from dungml.render.oldschool_blue import FLOOR, GRID, INK, PAGE, OldSchoolBlue

SVG_NS = "{http://www.w3.org/2000/svg}"


def _parse_svg(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def test_oldschool_blue_registered():
    assert "oldschool-blue" in list_renderers()
    assert get_renderer("oldschool-blue") is OldSchoolBlue


def test_renders_to_valid_svg(crypt_source):
    svg = render(parse(crypt_source), "oldschool-blue")
    assert _parse_svg(svg).tag == f"{SVG_NS}svg"


def test_ink_is_recoloured_blue(crypt_source):
    """The mono ink tokens (#111 / #fafafa) must all be remapped to the blue
    palette — none should survive in the output."""
    svg = render(parse(crypt_source), "oldschool-blue")
    assert INK in svg
    assert "#111" not in svg
    assert "#fafafa" not in svg


def test_solid_fill_page_when_no_background(quickstart_source):
    # quickstart declares no `background`, so the page falls to the solid blue
    # default; white floors are drawn on top so rooms read as carved rock.
    svg = render(parse(quickstart_source), "oldschool-blue")
    assert f'fill="{PAGE}"' in svg
    assert f'fill="{FLOOR}"' in svg


def test_no_grid_unless_declared(quickstart_source):
    # quickstart declares no grid_overlay → the blue style must not force one.
    svg = render(parse(quickstart_source), "oldschool-blue")
    assert 'class="map-grid"' not in svg


def test_declared_grid_is_tinted_blue():
    src = (
        'map "g" {\n'
        "  grid { bounds 20 x 20 }\n"
        "  grid_overlay 1\n"
        "}\n"
        'room "a" { rect 2,2 6 x 6 label "A" }\n'
    )
    svg = render(parse(src), "oldschool-blue")
    assert 'class="map-grid"' in svg
    assert f'stroke="{GRID}"' in svg
