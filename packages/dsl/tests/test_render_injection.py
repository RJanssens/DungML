"""Author-supplied strings must not be able to inject markup into the SVG.

The web editor inserts the rendered SVG as raw HTML and projects are shared
between members, so any value that reaches an attribute unescaped is a stored
XSS. Each case plants a payload in one DSL value and checks the output is
well-formed XML with no script element and no event-handler attribute.
"""
from __future__ import annotations

import re

import xml.etree.ElementTree as ET

import pytest

from dungml import parse
from dungml.render import get_renderer, list_renderers

# Breaks out of a double-quoted attribute, or of an element via `/>`.
Q = '\\"'
ATTR = f'red{Q} onmouseover={Q}alert(1)'
ELEM = f'x{Q}/><script>alert(1)</script><g a={Q}'

HEAD = 'map "M" { grid { bounds 20 x 20 } }\n'
CASES = {
    "room background": f'room "a" {{ rect 1,1 5 x 5 background "{ATTR}" }}',
    "corridor background": (
        f'corridor "c" {{ segment line from 1,1 to 9,1 background "{ATTR}" }}'
    ),
    "area background": f'area "p" {{ rect 1,1 3 x 3 background "{ATTR}" }}',
    "map background": (
        f'map "M" {{ grid {{ bounds 20 x 20 }} background "{ATTR}" }}'
    ),
    "marker tag": f'marker "m" at 3,3 tag "{ATTR}"',
    "feature_def background": (
        f'feature_def "f" {{ shape circle radius 1 background "{ATTR}" }}\n'
        'feature f at 3,3'
    ),
    "outline color": (
        f'feature_def "f" {{ shape circle radius 1 outline {{ color "{ATTR}" }} }}\n'
        'feature f at 3,3'
    ),
    "overlay fill": (
        f'feature_def "f" {{ shape circle radius 1 overlay circle radius 0.5 fill "{ATTR}" }}\n'
        'feature f at 3,3'
    ),
    "glyph fill-color": (
        f'feature_def "f" {{ glyph {{ circle plain at 0,0 radius 1 fill-color "{ATTR}" }} }}\n'
        'feature f at 3,3'
    ),
    "glyph stroke-color": (
        f'feature_def "f" {{ glyph {{ circle plain at 0,0 radius 1 stroke-color "{ATTR}" }} }}\n'
        'feature f at 3,3'
    ),
    "glyph class": (
        f'feature_def "f" {{ glyph {{ circle stroke at 0,0 radius 1 class "{ATTR}" }} }}\n'
        'feature f at 3,3'
    ),
    "glyph path": (
        f'feature_def "f" {{ glyph {{ path stroke "{ELEM}" }} }}\n'
        'feature f at 3,3'
    ),
    "room grid colour": f'room "a" {{ rect 1,1 5 x 5 grid 1 "{ATTR}" }}',
}


def _source(case: str) -> str:
    body = CASES[case]
    return body if body.startswith("map ") else HEAD + body


def _assert_inert(svg: str) -> None:
    root = ET.fromstring(svg)  # raises if the payload broke the markup
    for el in root.iter():
        assert not el.tag.endswith("script"), "script element injected"
        handlers = [k for k in el.attrib if k.lower().startswith("on")]
        assert handlers == [], f"event handler injected on <{el.tag}>"


@pytest.mark.parametrize("renderer", list_renderers())
@pytest.mark.parametrize("case", sorted(CASES))
def test_payload_is_inert(case: str, renderer: str) -> None:
    _assert_inert(get_renderer(renderer)().render(parse(_source(case))))


def test_legitimate_colours_still_pass_through() -> None:
    svg = get_renderer("classic-bw")().render(parse(
        HEAD
        + 'room "a" { rect 1,1 5 x 5 background "#3a5f7d" }\n'
        + 'room "b" { rect 7,1 5 x 5 background "rgb(10, 20, 30)" }\n'
        + 'room "c" { rect 13,1 5 x 5 background "stone" }\n'
        + 'marker "m" at 3,3 tag "tomato"'
    ))
    assert "fill:#3a5f7d" in svg
    assert "fill:rgb(10, 20, 30)" in svg
    assert re.search(r"url\(#dm-[0-9a-f]+-tx-stone\)", svg)
    assert 'fill="tomato"' in svg
