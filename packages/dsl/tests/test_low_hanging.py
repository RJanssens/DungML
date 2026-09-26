"""Small fixes from the second review: silent authoring mistakes now warn,
windows are visible, the hatched halo isn't clipped, and the legend shows
what the map actually uses."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from dungml import parse, render, validate

SVG = "{http://www.w3.org/2000/svg}"
H = 'include "core.dmap"\nmap "M" { grid { bounds 30 x 20 } }\n'
R2 = 'room "a" { rect 2,2 8 x 8 }\nroom "b" { rect 10,2 8 x 8 }\n'


def _warns(src: str) -> list[str]:
    return [d.message for d in validate(parse(src)) if d.severity == "warning"]


# 1 — a door not on any wall
def test_door_off_every_wall_warns() -> None:
    warns = _warns(H + R2 + "door at 5,5 { connects room.a, room.b }")
    assert any("door at (5.0, 5.0) is not on a wall" in m for m in warns), warns


@pytest.mark.parametrize("door", [
    "door at 10,6 { connects room.a, room.b }",  # on the shared wall
    "door at 10.6,6 { connects room.a, room.b }",  # a little off, still snaps
])
def test_door_on_a_wall_is_quiet(door: str) -> None:
    assert not any("not on a wall" in m for m in _warns(H + R2 + door))


def test_corridor_doors_count_as_on_a_wall() -> None:
    src = H + ('room "a" { rect 2,2 8 x 8 }\n'
               'corridor "k" { width 2 segment line from 10,5 to 20,5 }\n'
               'corridor "j" { segment line from 20,5 to 25,5 }\n'
               "door at 10,5 { connects room.a, corridor.k }\n"
               "door at 20,5 { connects corridor.k, corridor.j type open }\n"
               "door at 15,4 { connects corridor.k }\n")  # on k's side
    assert not any("not on a wall" in m for m in _warns(src))


# 2 — a window not on its room's wall (the renderer silently skips it)
def test_window_off_its_rooms_wall_warns() -> None:
    warns = _warns(H + R2 + "window at 5,5 { in room.a }")
    assert any("window at (5.0, 5.0) is not on a wall of room 'a'" in m for m in warns), warns
    assert not any("window" in m for m in _warns(H + R2 + "window at 2,5 { in room.a }"))


# 3 — room_numbers with a value it doesn't know
def test_unknown_room_numbers_value_warns() -> None:
    warns = _warns('map "M" { grid { bounds 9 x 9 } room_numbers of }')
    assert any("room_numbers 'of'" in m and "off" in m for m in warns), warns
    for ok in ("on", "off", "true", "false", "yes", "no"):
        src = f'map "M" {{ grid {{ bounds 9 x 9 }} room_numbers {ok} }}'
        assert not any("room_numbers" in m for m in _warns(src)), ok


# 4 — windows drawn as a framed pane as thick as the wall
def test_window_is_a_closed_pane_the_thickness_of_the_wall() -> None:
    root = ET.fromstring(render(parse(H + R2 + "window at 2,5 { in room.a width 2 }")))
    win = next(el for el in root.iter(f"{SVG}g") if el.get("class") == "window-instance")
    pane = next(el for el in win.iter(f"{SVG}polygon"))
    xs = sorted({float(v) for v in re.findall(r"([-\d.]+),[-\d.]+", pane.get("points"))})
    assert pytest.approx(xs[-1] - xs[0], abs=1e-6) == 0.18  # the wall stroke


# 5 — the hatched halo's roughen filter covers the whole canvas
def test_hatched_roughen_filter_is_not_clipped_to_the_shapes() -> None:
    svg = render(parse(open_sample("goblin_warren")))
    f = re.search(r'<filter id="[^"]*halo-roughen"[^>]*>', svg).group(0)
    assert 'filterUnits="userSpaceOnUse"' in f
    assert 'x="-5%"' not in f


def open_sample(name: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[3] / "samples" / f"{name}.dmap").read_text()


# 6 — the legend lists what the map uses
def test_legend_shows_only_what_the_map_uses() -> None:
    src = ('map "M" { grid { bounds 30 x 20 } legend }\n' + R2 +
           "door at 10,4 { connects room.a, room.b }\n"
           "door at 10,8 { connects room.a, room.b state locked }\n"
           "window at 2,5 { in room.a }\n")
    legend = render(parse(src)).split('class="legend"')[1]
    captions = re.findall(r">([A-Za-z-]{2,})</text>", legend)
    assert captions == ["Door", "Locked", "Window"]


def test_legend_with_nothing_to_show_keeps_the_full_key() -> None:
    src = 'map "M" { grid { bounds 30 x 20 } legend }\n' + R2
    legend = render(parse(src)).split('class="legend"')[1]
    assert len(re.findall(r">([A-Za-z-]{2,})</text>", legend)) == 11


# 7 — an explicitly placed label on top of a feature
def test_explicit_label_on_a_feature_warns() -> None:
    warns = _warns(H + 'room "s" { rect 1,1 12 x 8 label "Shrine" at 6,5 feature statue at 6,5 }')
    assert any("room 's' label" in m and "statue" in m for m in warns), warns
    assert not any("label" in m for m in _warns(
        H + 'room "s" { rect 1,1 12 x 8 label "Shrine" at 6,2 feature statue at 6,6 }'))


# (found while cleaning up) — a wide arc was sampled by its raw angle
# difference, before the sweep direction applied: 340° drawn in 12 steps.
def test_a_wide_arc_is_drawn_smoothly() -> None:
    src = ('map "M" { grid { bounds 30 x 30 } }\n'
           'slice "s" { kind split segment arc center 15,15 radius 8 '
           'from-angle 10 to-angle -10 sweep ccw }\n')
    d = re.search(r'class="slice slice-split"[^>]*\sd="([^"]+)"', render(parse(src))).group(1)
    assert d.count("L") >= 340 // 5  # about one point per 5°, like every other arc
