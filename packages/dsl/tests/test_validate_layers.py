"""Validation reaches into layers, and flags silent mistakes: duplicate names
and misspelt enum values (door type/state, line_style, corners, …).

New checks are warnings: the MCP authoring tools refuse any edit to a map
with an error diagnostic, so a new error class would lock existing maps.
Layer checks mirror the severity their top-level twin already has."""
from __future__ import annotations

import pytest

from dungml import parse, validate

HEAD = 'include "core.dmap"\nmap "M" { grid { bounds 40 x 20 } }\n'


def _msgs(src: str, severity: str) -> list[str]:
    return [d.message for d in validate(parse(HEAD + src)) if d.severity == severity]


# ---- layers ----

def test_door_into_layer_room_is_not_an_unknown_room() -> None:
    errs = _msgs(
        'room "a" { rect 1,1 5 x 5 }\n'
        'layer "sec" hidden { room "s" { rect 6,1 5 x 5 } }\n'
        'door at 6,3 { connects room.a, room.s type secret }\n',
        "error",
    )
    assert errs == []


def test_unknown_feature_in_layer_room_is_error() -> None:
    errs = _msgs('layer "L" { room "r" { rect 1,1 5 x 5 feature gargoyle at 2,2 } }', "error")
    assert any("gargoyle" in m for m in errs), errs


def test_layer_room_shape_is_checked() -> None:
    errs = _msgs('layer "L" { room "r" { rect 1,1 0 x 5 } }', "error")
    assert any("non-positive" in m for m in errs), errs


def test_layer_door_with_unknown_ref_is_error() -> None:
    errs = _msgs('layer "L" { door at 3,3 { connects room.nowhere } }', "error")
    assert any("nowhere" in m for m in errs), errs


def test_layer_window_with_unknown_room_is_error() -> None:
    errs = _msgs('layer "L" { window at 3,3 { in room.nowhere } }', "error")
    assert any("nowhere" in m for m in errs), errs


def test_layer_corridor_feature_is_checked() -> None:
    errs = _msgs(
        'layer "L" { corridor "c" { segment line from 1,1 to 9,1 feature gargoyle at 3,1 } }',
        "error",
    )
    assert any("gargoyle" in m for m in errs), errs


# ---- duplicate names ----

def test_duplicate_room_name_warns_with_both_lines() -> None:
    src = 'room "a" { rect 1,1 5 x 5 }\nroom "a" { rect 10,1 5 x 5 }\n'
    diags = [d for d in validate(parse(HEAD + src)) if "duplicate" in d.message]
    assert len(diags) == 1
    assert diags[0].severity == "warning"
    assert "room 'a'" in diags[0].message
    assert diags[0].line == 4  # points at the redefinition
    assert "line 3" in diags[0].message


def test_duplicate_name_across_top_level_and_layer_warns() -> None:
    warns = _msgs(
        'room "a" { rect 1,1 5 x 5 }\nlayer "L" { room "a" { rect 10,1 5 x 5 } }\n',
        "warning",
    )
    assert any("duplicate" in m and "room 'a'" in m for m in warns), warns


def test_duplicate_corridor_name_warns() -> None:
    warns = _msgs(
        'corridor "c" { segment line from 1,1 to 9,1 }\n'
        'corridor "c" { segment line from 1,5 to 9,5 }\n',
        "warning",
    )
    assert any("duplicate" in m and "corridor 'c'" in m for m in warns), warns


def test_include_override_is_not_a_duplicate() -> None:
    # The main file redefining an included feature_def is the documented way
    # to override a library default.
    warns = _msgs('feature_def "pillar" { shape circle radius 0.5 }\n', "warning")
    assert not any("duplicate" in m for m in warns), warns


# ---- misspelt enum values ----

ROOMS = 'room "a" { rect 1,1 5 x 5 }\nroom "b" { rect 6,1 5 x 5 }\n'


@pytest.mark.parametrize(
    "decl, needle, suggestion",
    [
        ("type woden", "door type 'woden'", "wooden"),
        ("state lokced", "door state 'lokced'", "locked"),
    ],
)
def test_unknown_door_vocabulary_warns_with_suggestion(
    decl: str, needle: str, suggestion: str
) -> None:
    warns = _msgs(ROOMS + f"door at 6,3 {{ connects room.a, room.b {decl} }}\n", "warning")
    hit = [m for m in warns if needle in m]
    assert hit and suggestion in hit[0], warns


def test_known_door_vocabulary_is_quiet() -> None:
    doors = "".join(
        f"door at 6,{y} {{ connects room.a, room.b type {t} state {s} }}\n"
        for y, (t, s) in enumerate(
            [("wooden", "closed"), ("iron", "locked"), ("arch", "open"),
             ("portcullis", "barred"), ("one-way", "stuck"), ("gates", "ajar")],
            start=1,
        )
    )
    warns = _msgs(ROOMS + doors, "warning")
    assert not any("door type" in m or "door state" in m for m in warns), warns


def test_unknown_line_style_warns() -> None:
    warns = _msgs('room "a" { rect 1,1 5 x 5 line_style orgainc }', "warning")
    assert any("line_style 'orgainc'" in m and "organic" in m for m in warns), warns


def test_unknown_corners_warns() -> None:
    warns = _msgs('corridor "c" { corners sharp segment line from 1,1 to 9,1 }', "warning")
    assert any("corners 'sharp'" in m for m in warns), warns


def test_samples_raise_no_vocabulary_warnings() -> None:
    from pathlib import Path

    samples = Path(__file__).resolve().parents[3] / "samples"
    noisy: list[str] = []
    for f in sorted(samples.glob("*.dmap")):
        dmap = parse(f.read_text(encoding="utf-8"), path=f)
        if dmap.scenario is not None:
            continue
        for d in validate(dmap):
            if any(k in d.message for k in ("door type", "door state", "line_style", "corners", "duplicate")):
                noisy.append(f"{f.name}: {d.message}")
    assert noisy == []
