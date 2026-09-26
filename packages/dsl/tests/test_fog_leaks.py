"""GM-only information must not survive into the fogged players' view."""
from __future__ import annotations

import re

from dungml import fog_of_war, parse, render_fogged

SRC = """
include "core.dmap"
map "M" { grid { bounds 40 x 20 } dm_notes "MAPNOTE" }
feature_def "snare" { secret shape circle radius 0.3 }
room "a" {
  rect 1,1 6 x 6 label "A" dm_notes "ROOMNOTE"
  feature pillar at 3,3 { dm_notes "FEATNOTE" }
  area "pool" kind water { rect 2,2 1 x 1 dm_notes "AREANOTE" }
  text "carving" at 4,4 { dm_notes "TEXTNOTE" }
  line_feature "rail" { point 2,5 point 5,5 dm_notes "LFNOTE" }
  exit at 5,2 { to "other" at 1,1 dm_notes "EXITNOTE" }
}
room "b" { rect 10,1 6 x 6 label "B" }
room "c" { rect 20,1 6 x 6 label "C" }
corridor "k" { segment line from 7,4 to 10,4 dm_notes "CORRNOTE" }
door at 7,4 { connects room.a, corridor.k dm_notes "DOORNOTE" }
door at 10,4 { connects corridor.k, room.b }
door at 16,4 { connects room.b, room.c }
marker "orc" at 4,5 dm_notes "MARKNOTE"
feature snare at 5,5
feature pillar at 6,6 { secret }
layer "deco" { feature snare at 4,2 feature pillar at 2,6 { secret } }
"""

DISCOVERED = {"room.a", "corridor.k", "room.c"}
DOORS = {"7,4"}

NOTES = [
    "MAPNOTE", "ROOMNOTE", "FEATNOTE", "AREANOTE", "TEXTNOTE", "LFNOTE",
    "EXITNOTE", "CORRNOTE", "DOORNOTE", "MARKNOTE",
]


def test_fogged_svg_carries_no_dm_notes() -> None:
    svg = render_fogged(parse(SRC), DISCOVERED, DOORS)
    leaked = [n for n in NOTES if n in svg]
    assert leaked == []


def test_fog_of_war_model_has_no_dm_notes() -> None:
    fogged = fog_of_war(parse(SRC), DISCOVERED, DOORS)
    dumped = fogged.model_dump_json()
    assert [n for n in NOTES if n in dumped] == []


def test_gm_view_keeps_dm_notes() -> None:
    svg = render_fogged(parse(SRC), DISCOVERED, DOORS, full=True)
    assert "ROOMNOTE" in svg and "DOORNOTE" in svg


def test_secret_features_outside_rooms_are_stripped() -> None:
    svg = render_fogged(parse(SRC), DISCOVERED, DOORS)
    # Only the one non-secret pillar inside room a may remain.
    assert 'data-ref="snare"' not in svg
    assert len(re.findall(r'data-ref="pillar"', svg)) == 1


def test_room_numbers_match_gm_view_under_fog() -> None:
    dmap = parse(SRC)
    gm = re.findall(r">(\d+\. [A-Z])<", render_fogged(dmap, DISCOVERED, DOORS, full=True))
    fog = re.findall(r">(\d+\. [A-Z])<", render_fogged(dmap, DISCOVERED, DOORS))
    assert gm == ["1. A", "2. B", "3. C"]
    assert fog == ["1. A", "3. C"]
