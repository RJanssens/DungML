"""Wall `line_style` rendering — ruined, dotted, dashed, trail."""
from __future__ import annotations

import re

from dungml import parse, render


def _render(src: str) -> str:
    return render(parse(src))


def _room(style: str) -> str:
    return _render(
        'map "M" { grid { bounds 20 x 20 } renderer "classic-bw" }\n'
        f'room "r" {{ rect 2,2 6 x 6 line_style {style} }}\n'
    )


def test_ruined_room_walls_get_ruined_class_and_dash_pattern():
    src = """
    map "M" { grid { bounds 20 x 20 } renderer "classic-bw" }
    room "ruin"  { rect 2,2 6 x 6 line_style ruined }
    room "solid" { rect 12,12 5 x 5 }
    """
    svg = _render(src)
    # The ruined room's wall group carries the class; the stylesheet defines
    # the dash-dot rule that the descendant selector applies to its walls.
    assert 'data-room="ruin" class="ruined"' in svg
    assert ".ruined .wall{stroke-dasharray:" in svg
    # A plain room's wall group is not tagged ruined.
    assert 'data-room="solid" class="ruined"' not in svg


def test_dotted_room_walls_get_dotted_class_and_rule():
    svg = _room("dotted")
    assert 'data-room="r" class="dotted"' in svg
    assert ".dotted .wall{stroke-dasharray:" in svg


def test_dashed_room_walls_get_dashed_class_and_rule():
    svg = _room("dashed")
    assert 'data-room="r" class="dashed"' in svg
    assert ".dashed .wall{stroke-dasharray:" in svg


def test_trail_room_draws_x_marks_not_a_dash_class():
    svg = _room("trail")
    # Trail draws its own x-marks; the group is NOT tagged with a dash class.
    assert 'data-room="r" class="trail"' not in svg
    assert ".trail-x{" in svg  # stylesheet rule present
    marks = svg.count('class="trail-x"')
    assert marks > 4  # several x's spaced around a 6x6 room's perimeter
    # Each x-mark is two crossing strokes (two M…L subpaths).
    a_mark = re.search(r'class="trail-x" d="(M[^"]+)"', svg)
    assert a_mark and a_mark.group(1).count("M") == 2


def test_line_styles_round_trip_through_parser():
    for style in ("ruined", "dotted", "dashed", "trail"):
        m = parse(
            'map "M" { grid { bounds 10 x 10 } }\n'
            f'room "r" {{ rect 1,1 4 x 4 line_style {style} }}\n'
        )
        assert m.rooms["r"].line_style == style
