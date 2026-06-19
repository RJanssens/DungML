"""Non-uniform feature scaling — `scale X:Y`."""
from __future__ import annotations

import re

from dungml import parse, render, validate

_LIB = 'feature_def "dot" { glyph { circle plain at 0,0 radius 0.3 } }\n'


def _map(feature_line: str) -> str:
    return (
        'map "M" { grid { bounds 10 x 10 } renderer "classic-bw" }\n'
        + _LIB
        + feature_line
        + "\n"
    )


def test_uniform_scale_unchanged():
    fi = parse(_map("feature dot at 5,5 scale 2")).features[0]
    assert fi.scale == 2.0 and fi.scale_y is None


def test_xy_scale_parses():
    fi = parse(_map("feature dot at 5,5 scale 3:1")).features[0]
    assert fi.scale == 3.0 and fi.scale_y == 1.0


def test_xy_scale_render_transform():
    svg = render(parse(_map("feature dot at 5,5 scale 3:1")))
    assert "scale(3,1)" in svg


def test_uniform_scale_render_transform():
    svg = render(parse(_map("feature dot at 5,5 scale 2")))
    assert "scale(2,2)" in svg


def test_negative_y_scale_errors():
    diags = validate(parse(_map("feature dot at 5,5 scale 2:0")))
    assert any(
        d.severity == "error" and "scale must be positive" in d.message
        for d in diags
    )
