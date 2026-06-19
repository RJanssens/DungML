"""Built-in `floor-trapdoor` / `ceiling-trapdoor` — circle with F / C."""
from __future__ import annotations

import re

from dungml import parse, render, validate


def _svg(ref: str) -> str:
    return render(
        parse(
            'include "core.dmap"\n'
            'map "M" { grid { bounds 6 x 6 } renderer "classic-bw" }\n'
            f"feature {ref} at 3,3\n"
        )
    )


def _body(svg: str, ref: str) -> str:
    m = re.search(rf'data-ref="{re.escape(ref)}".*?</g>', svg, re.S)
    assert m, f"{ref} not rendered"
    return m.group(0)


def test_trapdoors_defined_and_valid():
    m = parse(
        'include "core.dmap"\n'
        'map "M" { grid { bounds 6 x 6 } }\n'
        "feature floor-trapdoor at 2,2\n"
        "feature ceiling-trapdoor at 4,4\n"
    )
    assert "floor-trapdoor" in m.feature_defs
    assert "ceiling-trapdoor" in m.feature_defs
    assert all(d.severity != "error" for d in validate(m))


def test_floor_trapdoor_is_circle_with_F_lines():
    body = _body(_svg("floor-trapdoor"), "floor-trapdoor")
    assert body.count("<circle") == 1
    assert body.count("<line") == 3  # the F: stem + two bars


def test_ceiling_trapdoor_is_circle_with_C_path():
    body = _body(_svg("ceiling-trapdoor"), "ceiling-trapdoor")
    assert body.count("<circle") == 1
    assert body.count("<path") == 1  # the C arc


def test_trapdoor_without_include_errors():
    m = parse('map "M" { grid { bounds 6 x 6 } }\nfeature floor-trapdoor at 3,3\n')
    assert any(
        d.severity == "error" and "floor-trapdoor" in d.message
        and "core.dmap" in d.message
        for d in validate(m)
    )
