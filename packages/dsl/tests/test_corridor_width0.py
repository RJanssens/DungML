"""Zero-width corridors render as a single centerline (a route line)."""
from __future__ import annotations

from dungml import parse, render, validate


def _corridor_src(width: float) -> str:
    return (
        'map "M" { grid { bounds 20 x 10 } renderer "classic-bw" }\n'
        f'corridor "c" {{ width {width} segment line from 2,5 to 18,5 }}\n'
    )


def test_width_zero_is_valid():
    diags = validate(parse(_corridor_src(0)))
    assert not any(d.severity == "error" for d in diags)


def test_negative_width_still_errors():
    diags = validate(parse(_corridor_src(-1)))
    assert any(
        d.severity == "error" and "negative width" in d.message for d in diags
    )


def test_width_zero_renders_single_line():
    svg = render(parse(_corridor_src(0)))
    # A single dark centerline stroke — no floor band layer.
    assert svg.count('class="corridor-wall"') == 1
    assert 'class="corridor-floor"' not in svg


def test_normal_width_keeps_wall_and_floor_layers():
    svg = render(parse(_corridor_src(1)))
    assert svg.count('class="corridor-wall"') == 1
    assert svg.count('class="corridor-floor"') == 1


def test_width_zero_trail_draws_x_marks():
    svg = render(
        parse(
            'map "M" { grid { bounds 20 x 10 } renderer "classic-bw" }\n'
            'corridor "c" { width 0 line_style trail '
            "segment line from 2,5 to 18,5 }\n"
        )
    )
    assert svg.count('class="trail-x"') > 4
    # No solid centerline stroke for an all-line trail corridor.
    assert 'class="corridor-wall"' not in svg


def test_width_zero_dashed_gets_dash_array():
    svg = render(
        parse(
            'map "M" { grid { bounds 20 x 10 } renderer "classic-bw" }\n'
            'corridor "c" { width 0 line_style dashed '
            "segment line from 2,5 to 18,5 }\n"
        )
    )
    # Single dashed centerline.
    assert svg.count('class="corridor-wall"') == 1
    assert "stroke-dasharray" in svg
