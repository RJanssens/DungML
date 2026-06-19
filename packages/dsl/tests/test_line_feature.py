"""`line_feature` — bars (dotted), curtain (wavy), barred (+ marks)."""
from __future__ import annotations

from dungml import parse, render, validate


def _map(body: str) -> str:
    return (
        'map "M" { grid { bounds 12 x 9 } renderer "classic-bw" }\n'
        'room "r" { rect 0,0 12 x 9 }\n' + body + "\n"
    )


def test_parses_points_and_kind():
    m = parse(_map('line_feature "f" { kind curtain point 1,2 point 8,2 point 8,6 }'))
    lf = m.line_features[0]
    assert lf.kind == "curtain"
    assert lf.points == [(1.0, 2.0), (8.0, 2.0), (8.0, 6.0)]


def test_inline_kind_form():
    m = parse(_map('line_feature "f" kind bars { point 1,2 point 8,2 }'))
    assert m.line_features[0].kind == "bars"


def test_bars_render_dotted():
    svg = render(parse(_map('line_feature "f" { kind bars point 1,2 point 10,2 }')))
    assert 'data-kind="bars"' in svg
    assert "stroke-dasharray" in svg


def test_curtain_render_is_a_wavy_path():
    svg = render(parse(_map('line_feature "f" { kind curtain point 1,2 point 10,2 }')))
    # A single multi-vertex path (the sine wiggle) tagged as a curtain.
    assert 'data-kind="curtain"' in svg
    assert svg.count('class="line-feature"') == 1


def test_barred_render_plus_marks():
    svg = render(parse(_map('line_feature "f" { kind barred point 1,2 point 9,2 }')))
    # Several `+` marks (each a class="line-feature" path with two strokes).
    assert svg.count('class="line-feature"') > 4


def test_single_point_is_an_error():
    diags = validate(parse(_map('line_feature "f" { kind bars point 3,3 }')))
    assert any(
        d.severity == "error" and "at least 2" in d.message for d in diags
    )


def test_unknown_kind_warns():
    diags = validate(
        parse(_map('line_feature "f" { kind squiggle point 1,2 point 8,2 }'))
    )
    assert any(
        d.severity == "warning" and "unknown kind" in d.message for d in diags
    )


def test_valid_line_feature_clean():
    diags = validate(
        parse(_map('line_feature "f" { kind barred point 1,2 point 8,2 }'))
    )
    assert not any(d.severity == "error" for d in diags)
