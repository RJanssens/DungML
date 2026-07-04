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


def test_party_start_unknown_ref_errors():
    src = (
        'map "M" { grid { bounds 10 x 10 } party_start "ghost" }\n'
        'room "vault" { rect 0,0 4 x 4 }'
    )
    diags = validate(parse(src))
    msgs = [d.message for d in diags if d.severity == "error"]
    assert any("party_start" in m and "ghost" in m for m in msgs)


def test_party_start_valid_refs_and_coords_ok():
    # room ref, corridor ref, and bare coords each produce no party_start error.
    for ps in ('party_start "vault"', 'party_start "hall"', "party_start 1,1"):
        src = (
            f'map "M" {{ grid {{ bounds 20 x 20 }} {ps} }}\n'
            'room "vault" { rect 0,0 4 x 4 }\n'
            'corridor "hall" { width 1 node n1 at 8,1 node n2 at 12,1 run n1 to n2 }'
        )
        diags = validate(parse(src))
        assert not [d for d in diags if "party_start" in d.message], ps
