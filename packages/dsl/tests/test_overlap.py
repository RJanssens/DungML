"""Tests for the overlapping-area validation warning."""
from __future__ import annotations

from pathlib import Path

import pytest

from dungml import parse, validate
from dungml.geometry import polygons_overlap


def _overlap_warnings(src: str):
    return [
        d
        for d in validate(parse(src))
        if d.severity == "warning" and "overlap" in d.message
    ]


def test_overlapping_rects_warn():
    src = """
    map "M" { grid { bounds 40 x 40 } }
    room "a" { rect 2,2 10 x 10 }
    room "b" { rect 8,8 10 x 10 }
    """
    warns = _overlap_warnings(src)
    assert len(warns) == 1
    assert "room 'a'" in warns[0].message and "room 'b'" in warns[0].message


def test_allow_overlap_suppresses_warning():
    # `b` is flagged allow_overlap, so the a/b overlap is not reported even
    # though their interiors clearly intersect.
    src = """
    map "M" { grid { bounds 40 x 40 } }
    room "a" { rect 2,2 10 x 10 }
    room "b" { rect 8,8 10 x 10 allow_overlap }
    """
    assert _overlap_warnings(src) == []
    assert parse(src).rooms["b"].allow_overlap is True


def test_allow_overlap_on_one_room_covers_all_its_overlaps():
    # The cave floor is exempt; both the building stacked on it AND a second
    # overlap stay silent. A pair between two non-exempt rooms still warns.
    src = """
    map "M" { grid { bounds 60 x 60 } }
    room "cave" { polygon (0,0) (40,0) (40,40) (0,40) allow_overlap }
    room "building" { rect 5,5 8 x 6 }
    room "hut" { rect 20,20 6 x 6 }
    """
    # cave overlaps both building and hut, but cave is exempt → no warnings.
    assert _overlap_warnings(src) == []


def test_adjacent_rooms_sharing_a_wall_do_not_warn():
    # b starts exactly where a ends (x=12): they share a wall, no overlap.
    src = """
    map "M" { grid { bounds 40 x 40 } }
    room "a" { rect 2,2 10 x 10 }
    room "b" { rect 12,2 10 x 10 }
    """
    assert _overlap_warnings(src) == []


def test_fully_contained_room_warns():
    src = """
    map "M" { grid { bounds 40 x 40 } }
    room "outer" { rect 2,2 20 x 20 }
    room "inner" { rect 6,6 4 x 4 }
    """
    assert len(_overlap_warnings(src)) == 1


def test_identical_rooms_warn():
    src = """
    map "M" { grid { bounds 40 x 40 } }
    room "a" { rect 5,5 8 x 8 }
    room "b" { rect 5,5 8 x 8 }
    """
    assert len(_overlap_warnings(src)) == 1


def test_corridor_overlapping_room_warns():
    src = """
    map "M" { grid { bounds 40 x 40 } }
    room "a" { rect 2,2 10 x 10 }
    corridor "c" { width 2 segment line from 5,5 to 20,5 }
    """
    warns = _overlap_warnings(src)
    assert len(warns) == 1
    assert "corridor 'c'" in warns[0].message


def test_corridor_touching_room_wall_does_not_warn():
    # Corridor runs from the room's right wall (x=12) outward — just touches.
    src = """
    map "M" { grid { bounds 40 x 40 } }
    room "a" { rect 2,2 10 x 10 }
    corridor "c" { width 2 segment line from 12,7 to 20,7 }
    """
    assert _overlap_warnings(src) == []


def test_tiny_overlap_below_threshold_does_not_warn():
    # Corridor pokes 0.5 units into the room (width 1 → ~0.5 sq) — a normal
    # connection sliver, under the ~1.0 sq threshold.
    src = """
    map "M" { grid { bounds 40 x 40 } }
    room "a" { rect 2,2 10 x 10 }
    corridor "c" { width 1 segment line from 11.5,7 to 20,7 }
    """
    assert _overlap_warnings(src) == []


def test_warning_reports_area():
    src = """
    map "M" { grid { bounds 40 x 40 } }
    room "a" { rect 2,2 10 x 10 }
    room "b" { rect 8,8 10 x 10 }
    """
    warns = _overlap_warnings(src)
    assert len(warns) == 1
    assert "sq units" in warns[0].message


def test_overlap_is_warning_not_error():
    src = """
    map "M" { grid { bounds 40 x 40 } }
    room "a" { rect 2,2 10 x 10 }
    room "b" { rect 8,8 10 x 10 }
    """
    diags = validate(parse(src))
    assert not any(d.severity == "error" for d in diags)


def test_polygons_overlap_primitive():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    overlapping = [(5, 5), (15, 5), (15, 15), (5, 15)]
    touching = [(10, 0), (20, 0), (20, 10), (10, 10)]
    assert polygons_overlap(sq, overlapping) is True
    assert polygons_overlap(sq, touching) is False


def test_maze_of_connecting_corridors_has_no_overlap_warnings():
    """maze.dmap is built entirely from corridors meeting at bends — every
    overlap is a sub-threshold junction sliver, so none should warn."""
    src = Path("samples/maze.dmap").read_text(encoding="utf-8")
    assert _overlap_warnings(src) == []


@pytest.mark.parametrize("sample", sorted(Path("samples").glob("*.dmap")))
def test_no_subthreshold_overlap_noise_in_samples(sample):
    """Any overlap warning a sample does produce must clear the threshold —
    guards against cosmetic connection slivers leaking through."""
    src = sample.read_text(encoding="utf-8")
    try:
        dmap = parse(src)
    except Exception:
        pytest.skip(f"{sample.name} is not a standalone map")
    import re

    from dungml.validate import OVERLAP_MIN_AREA

    for d in validate(dmap):
        if d.severity == "warning" and "overlap" in d.message:
            m = re.search(r"~([\d.]+) sq", d.message)
            assert m, d.message
            assert float(m.group(1)) >= OVERLAP_MIN_AREA, f"{sample.name}: {d.message}"
