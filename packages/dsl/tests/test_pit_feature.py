"""The built-in `pit` feature: white square, inner black square, corner lines."""
from __future__ import annotations

import re

from dungml import parse, render, validate


def _pit_svg() -> str:
    return render(
        parse(
            'include "core.dmap"\n'
            'map "M" { grid { bounds 6 x 6 } renderer "classic-bw" }\n'
            "feature pit at 3,3\n"
        )
    )


def test_pit_is_a_builtin_via_core():
    m = parse(
        'include "core.dmap"\n'
        'map "M" { grid { bounds 6 x 6 } }\n'
        "feature pit at 3,3\n"
    )
    assert "pit" in m.feature_defs
    assert all(d.severity != "error" for d in validate(m))


def test_pit_renders_two_squares_and_corner_lines():
    body = _pit_svg()
    # The feature instance group for the pit.
    grp = re.search(r'data-ref="pit".*?</g>', body, re.S)
    assert grp, "pit feature instance not rendered"
    g = grp.group(0)
    # Outer white-fill/black-stroke square (.feature) + inner black square
    # (.feature-fill), plus the four corner lines.
    assert g.count("<rect") == 2
    assert 'class="feature-fill"' in g  # inner solid square
    assert g.count("<line") == 4


def test_pit_without_include_errors():
    m = parse(
        'map "M" { grid { bounds 6 x 6 } }\nfeature pit at 3,3\n'
    )
    assert any(
        d.severity == "error" and "pit" in d.message and "core.dmap" in d.message
        for d in validate(m)
    )
