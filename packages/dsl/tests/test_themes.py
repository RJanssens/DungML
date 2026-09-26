"""Themes: the palette + font a renderer draws with, selectable per map.

A renderer is geometry + a default theme (classic-bw → mono, hatched →
paper, oldschool-blue → blue). `theme NAME` in the map block swaps the
palette without changing the geometry — `renderer "hatched" theme blue`.
"""
from __future__ import annotations

import re

import pytest

from dungml import parse, render, validate
from dungml.render.theme import THEMES, Theme, get_theme, list_themes

BASE = """
include "core.dmap"
map "M" {{ grid {{ bounds 20 x 12 }} {extra} }}
room "a" {{ rect 1,1 6 x 6 label "A" feature pillar at 3,3 }}
room "b" {{ rect 9,1 6 x 6 label "B" }}
door at 7,4 {{ connects room.a, room.b type wooden state locked }}
"""


def _svg(extra: str = "", renderer: str | None = None) -> str:
    return render(parse(BASE.format(extra=extra)), renderer)


def test_builtin_themes_are_listed() -> None:
    assert {"mono", "paper", "blue"} <= set(list_themes())
    assert isinstance(get_theme("blue"), Theme)
    assert get_theme("nope") is None


@pytest.mark.parametrize(
    "renderer, theme",
    [("classic-bw", "mono"), ("floorplan", "mono"), ("hatched", "paper"),
     ("oldschool-blue", "blue")],
)
def test_renderer_default_theme_equals_explicit_theme(renderer: str, theme: str) -> None:
    assert _svg(renderer=renderer) == _svg(f"theme {theme}", renderer=renderer)


def test_theme_keyword_recolours_classic_geometry() -> None:
    blue = THEMES["blue"]
    svg = _svg("theme blue")
    assert f"stroke:{blue.ink}" in svg  # walls
    assert f'fill="{blue.page}"' in svg  # page background
    assert f"fill:{blue.floor}" in svg  # room floors
    assert "#111" not in svg
    # Geometry is still classic-bw: no hatch halo.
    assert "hatch-halo" not in svg


def test_hatched_geometry_with_blue_theme() -> None:
    blue = THEMES["blue"]
    svg = _svg("theme blue", renderer="hatched")
    assert "hatch-halo" in svg
    hatch = re.search(r'<pattern id="[^"]*hatch"[^>]*>.*?</pattern>', svg).group(0)
    assert blue.hatch in hatch


def test_font_comes_from_the_theme() -> None:
    svg = _svg("theme blue")
    fonts = set(re.findall(r'font-family(?::|=")([^;"]+)', svg))
    assert fonts == {THEMES["blue"].font}


def test_unknown_theme_warns_and_falls_back_to_the_renderer_default() -> None:
    src = BASE.format(extra="theme bleu")
    warns = [d.message for d in validate(parse(src)) if d.severity == "warning"]
    assert any("theme 'bleu'" in m and "blue" in m for m in warns), warns
    assert render(parse(src)) == _svg()


def test_theme_keyword_parses_onto_the_map_config() -> None:
    assert parse(BASE.format(extra="theme paper")).map.theme == "paper"
    assert parse(BASE.format(extra="")).map.theme is None
