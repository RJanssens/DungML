"""Every drawn entity carries its source range (`data-src="L:C-L:C"`) so the
editor can highlight what the cursor is on — the innermost range containing
the cursor wins, which picks a feature over the room around it even on one
line. The fogged players' view carries none (line gaps would hint at what
is hidden)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from dungml import parse, render, render_fogged

SVG = "{http://www.w3.org/2000/svg}"
SRC = """include "core.dmap"
map "M" { grid { bounds 40 x 20 } }
room "a" {
  rect 1,1 8 x 8
  label "A"
  feature pillar at 3,3
  area "pool" kind water { rect 5,5 2 x 2 }
  text "carving" at 4,7
}
room "b" { rect 12,1 6 x 6 feature statue at 14,3 }
corridor "k" { width 2 segment line from 9,5 to 12,5 label "Hall" }
door at 9,5 { connects room.a, corridor.k }
door at 12,5 { connects corridor.k, room.b type arch }
window at 1,4 { in room.a }
marker "orc" at 6,3
exit at 16,5 { to "below" at 1,1 }
line_feature "rail" { point 13,6 point 17,6 }
slice "crack" { kind split segment line from 20,1 to 20,18 }
"""


def _src_of(el: ET.Element) -> tuple[int, int, int, int] | None:
    v = el.get("data-src")
    if v is None:
        return None
    m = re.fullmatch(r"(\d+):(\d+)-(\d+):(\d+)", v)
    assert m, v
    return tuple(int(g) for g in m.groups())  # type: ignore[return-value]


def _anchored(svg: str) -> dict[tuple[int, int, int, int], list[ET.Element]]:
    out: dict = {}
    for el in ET.fromstring(svg).iter():
        s = _src_of(el)
        if s is not None:
            out.setdefault(s, []).append(el)
    return out


def _lines(svg: str) -> set[int]:
    return {s[0] for s in _anchored(svg)}


def test_every_entity_kind_is_anchored_to_its_source_line() -> None:
    lines = _lines(render(parse(SRC)))
    expected = {
        3,   # room a
        6,   # its pillar
        7,   # its pool
        8,   # its text
        10,  # room b (and, on the same line, its statue — see below)
        11,  # corridor k
        12, 13,  # doors
        14,  # window
        15,  # marker
        16,  # exit
        17,  # line feature
        18,  # slice
    }
    assert expected <= lines, sorted(expected - lines)


def test_room_parts_share_one_anchor() -> None:
    by_src = _anchored(render(parse(SRC)))
    room_a = next(els for s, els in by_src.items() if s[0] == 3)
    kinds = {(el.tag.removeprefix(SVG), el.get("class")) for el in room_a}
    assert ("path", "floor") in kinds  # the floor
    assert any(t == "g" for t, _ in kinds)  # its walls
    assert ("text", "label") in kinds  # its label


def test_nested_feature_on_the_same_line_has_the_narrower_range() -> None:
    by_src = _anchored(render(parse(SRC)))
    on_line_10 = sorted(by_src, key=lambda s: (s[0], s[1]))
    room_b = next(s for s in on_line_10 if s[0] == 10 and s[1] == 1)
    statue = next(s for s in on_line_10 if s[0] == 10 and s[1] > 1)
    assert room_b[1] < statue[1] and statue[3] <= room_b[3]  # nested inside
    assert any(el.get("data-ref") == "statue" for el in by_src[statue])


def test_fogged_view_carries_no_source_anchors() -> None:
    svg = render_fogged(parse(SRC), {"room.a", "corridor.k", "room.b"}, {"9,5", "12,5"})
    assert "data-src=" not in svg
