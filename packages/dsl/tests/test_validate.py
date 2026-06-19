"""Semantic validator tests."""
from __future__ import annotations

from dungml import parse, validate


def _errors(diags):
    return [d for d in diags if d.severity == "error"]


def _warnings(diags):
    return [d for d in diags if d.severity == "warning"]


def test_samples_validate_clean(crypt_source: str, cottage_source: str) -> None:
    for src in (crypt_source, cottage_source):
        diags = validate(parse(src))
        assert _errors(diags) == [], [str(d) for d in diags]


def test_unknown_feature_ref_is_error() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "r" {
      rect 1,1 5 x 5
      feature gargoyle at 3,3
    }
    """
    diags = validate(parse(src))
    errs = _errors(diags)
    assert any("gargoyle" in e.message for e in errs)


def test_custom_feature_def_satisfies_ref() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    feature_def "gargoyle" { shape circle radius 0.5 }
    room "r" {
      rect 1,1 5 x 5
      feature "gargoyle" at 3,3
    }
    """
    assert _errors(validate(parse(src))) == []


def test_door_references_unknown_room_is_error() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "a" { rect 1,1 5 x 5 }
    door at 6,3 { connects room.a, room.ghost  type arch }
    """
    errs = _errors(validate(parse(src)))
    assert any("ghost" in e.message for e in errs)


def test_door_malformed_ref_is_error() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "a" { rect 1,1 5 x 5 }
    door at 6,3 { connects bogus.a  type arch }
    """
    assert _errors(validate(parse(src)))


def test_window_in_unknown_room_is_error() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "a" { rect 1,1 5 x 5 }
    window at 3,1 { in room.b }
    """
    assert _errors(validate(parse(src)))


def test_corridor_without_segments_warns() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 30 x 30 } renderer "x" }
    corridor "c" { width 2 }
    """
    warns = _warnings(validate(parse(src)))
    assert any("no segments" in w.message for w in warns)


def test_out_of_bounds_feature_warns() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 10 x 10 } renderer "x" }
    room "r" {
      rect 1,1 5 x 5
      feature pillar at 50,50
    }
    """
    warns = _warnings(validate(parse(src)))
    assert any("outside the map bounds" in w.message for w in warns)


def test_polygon_room_with_two_points_is_error() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "r" { polygon (1,1) (5,5) }
    """
    assert _errors(validate(parse(src)))


def test_negative_scale_is_error() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "r" {
      rect 1,1 5 x 5
      feature pillar at 3,3 scale -1
    }
    """
    assert _errors(validate(parse(src)))
