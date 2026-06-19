"""Glyph feature_defs: parsing, rendering, and the bundled `core.dmap` library.

The built-in features (pillar, stairs, fountain, …) used to be bespoke
Python glyph functions; they now live in `includes/core.dmap` as `glyph`
feature_defs that a map brings in with `include "core.dmap"`.
`golden_builtin_glyphs.json` is a frozen snapshot of the original Python
output — the fidelity test asserts the library renders each built-in
equivalently, so the migration stays lossless even as the renderer evolves.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from dungml.errors import DmapParseError
from dungml.model import GlyphCircle, GlyphPath, GlyphPolygon
from dungml.parser import parse
from dungml.render.classic_bw import ClassicBW
from dungml.validate import validate

SVG_NS = "{http://www.w3.org/2000/svg}"
# Serialize children without an `ns0:` prefix so fragments re-parse cleanly.
ET.register_namespace("", "http://www.w3.org/2000/svg")
GOLDEN = json.loads(
    (Path(__file__).parent / "data" / "golden_builtin_glyphs.json").read_text()
)

_NUMERIC_ATTRS = {
    "cx", "cy", "r", "x", "y", "width", "height", "rx",
    "x1", "y1", "x2", "y2", "stroke-width", "points", "d",
}


def _normalize(fragment: str) -> list:
    """Parse an SVG body into a comparable, order-preserving form.

    Numbers are rounded so formatting differences (`0.070` vs `0.07`,
    `-0` vs `0`) don't register as changes; attribute order is sorted.
    """
    frag = re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", fragment)
    root = ET.fromstring(f"<g>{frag}</g>")
    out = []
    for el in root:
        attrs = {}
        for k, v in el.attrib.items():
            key = k.split("}")[-1]
            if key in _NUMERIC_ATTRS:
                v = re.sub(
                    r"-?\d+\.?\d*",
                    lambda m: format(float(m.group()), ".3f"),
                    v,
                )
            attrs[key] = re.sub(r"\s+", " ", v).strip()
        out.append((el.tag.split("}")[-1], tuple(sorted(attrs.items()))))
    return out


def _feature_bodies(svg: str) -> dict[str, str]:
    """Map data-ref -> inner SVG of every feature-instance group."""
    root = ET.fromstring(svg)
    bodies = {}
    for g in root.iter(f"{SVG_NS}g"):
        if g.get("class") == "feature-instance":
            inner = "".join(ET.tostring(c, encoding="unicode") for c in g)
            bodies[g.get("data-ref")] = inner
    return bodies


# A minimal map that brings in the built-in library.
_CORE = parse('include "core.dmap"\nmap "X" { grid { cell 10 px bounds 10 x 10 } }')


def test_core_library_defines_every_builtin():
    assert set(GOLDEN).issubset(_CORE.feature_defs)
    for name in GOLDEN:
        fd = _CORE.feature_defs[name]
        assert fd.glyph and fd.shape is None  # all built-ins are glyph defs


def test_builtin_glyphs_render_like_golden():
    names = list(GOLDEN)
    lines = ['include "core.dmap"', 'map "X" { grid { cell 10 px bounds 200 x 200 } }']
    for i, n in enumerate(names):
        lines.append(f'feature "{n}" at {(i % 20) + 1},{(i // 20) + 1}')
    bodies = _feature_bodies(ClassicBW().render(parse("\n".join(lines))))
    for name, gold in GOLDEN.items():
        assert name in bodies, f"{name} did not render"
        assert _normalize(bodies[name]) == _normalize(gold), name


def test_builtin_without_include_is_an_error():
    """Built-ins are no longer implicit: using one without the include errors."""
    m = parse('map "X" { grid { cell 10 px bounds 40 x 30 } }\nfeature pillar at 5,5')
    errs = [d for d in validate(m) if d.severity == "error"]
    assert any("pillar" in d.message and "core.dmap" in d.message for d in errs)


def test_builtin_with_include_validates_clean():
    src = (
        'include "core.dmap"\n'
        'map "X" { grid { cell 10 px bounds 40 x 30 } }\n'
        "feature pillar at 5,5"
    )
    assert all(d.severity != "error" for d in validate(parse(src)))


def test_local_def_overrides_library():
    """A local feature_def beats the included library — the toggle mechanism."""
    src = """
    include "core.dmap"
    map "X" { grid { cell 10 px bounds 40 x 30 } }
    feature_def "pillar" { shape circle radius 0.4 background "#abcdef" }
    feature pillar at 5,5
    """
    fd = parse(src).feature_defs["pillar"]
    assert fd.shape is not None and fd.background == "#abcdef"
    assert not fd.glyph  # the local (shape) def won, not the library glyph


def test_parse_custom_glyph_feature_def():
    src = """
    map "X" { grid { cell 10 px bounds 40 x 30 } }
    feature_def "rune" {
      glyph {
        circle stroke at 0,0 radius 0.4
        polygon fill (0,-0.2) (0.2,0.1) (-0.2,0.1)
        path stroke "M0,0 L1,1" fill-color "none"
        line stroke from -0.3,0 to 0.3,0 stroke-width 0.12
      }
    }
    feature "rune" at 5,5
    """
    g = parse(src).feature_defs["rune"].glyph
    assert [e.kind for e in g] == ["circle", "polygon", "path", "line"]
    assert isinstance(g[0], GlyphCircle) and g[0].role == "stroke" and g[0].r == 0.4
    assert isinstance(g[1], GlyphPolygon) and g[1].role == "fill"
    assert isinstance(g[2], GlyphPath) and g[2].fill == "none"
    assert g[3].stroke_width == 0.12


def test_glyph_renders_with_expected_classes():
    src = """
    map "X" { grid { cell 10 px bounds 40 x 30 } }
    feature_def "rune" {
      glyph {
        circle stroke at 0,0 radius 0.4
        circle fill at 0,0 radius 0.1
        circle plain at 0,0 radius 0.2 fill-color "#fff" stroke-color "none"
      }
    }
    feature "rune" at 5,5
    """
    body = _feature_bodies(ClassicBW().render(parse(src)))["rune"]
    assert 'class="feature"' in body
    assert 'class="feature-fill"' in body
    # plain → no class, explicit overrides only
    assert 'fill="#fff"' in body and 'stroke="none"' in body


def test_extra_class_is_appended():
    src = """
    map "X" { grid { cell 10 px bounds 40 x 30 } }
    feature_def "deck" {
      glyph { rect stroke at -0.8,-0.5 1.6 x 1.0 class "bridge-deck" }
    }
    feature "deck" at 5,5
    """
    body = _feature_bodies(ClassicBW().render(parse(src)))["deck"]
    assert 'class="feature bridge-deck"' in body


def test_feature_def_requires_shape_or_glyph():
    with pytest.raises(DmapParseError, match="must have a .shape. or a .glyph."):
        parse('map "X" { grid { cell 10 px bounds 40 x 30 } }\nfeature_def "x" {}')


def test_feature_def_rejects_both_shape_and_glyph():
    src = (
        'map "X" { grid { cell 10 px bounds 40 x 30 } }\n'
        'feature_def "x" { shape circle radius 1 glyph { circle fill at 0,0 radius 1 } }'
    )
    with pytest.raises(DmapParseError, match="has both a .shape. and a .glyph."):
        parse(src)


def test_glyph_polygon_arity_validated():
    src = """
    map "X" { grid { cell 10 px bounds 40 x 30 } }
    feature_def "bad" { glyph { polygon fill (0,0) (1,1) } }
    feature "bad" at 5,5
    """
    diags = validate(parse(src))
    assert any("at least 3" in d.message and d.severity == "error" for d in diags)
