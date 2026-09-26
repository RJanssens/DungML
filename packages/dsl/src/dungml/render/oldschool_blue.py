"""oldschool-blue — classic blue-ink dungeon-map style.

Blue line-work over a solid blue page, with white room/corridor floors —
the look of the hand-inked blue dungeon maps from early tabletop modules
(and the blue "map symbol" sheets hobbyists still draw today). The negative
space around the explorable area is a flat fill, so the white rooms read as
carved out of solid rock. A `grid_overlay` (if the map declares one) takes
the theme's blue grid colour unless the author picks another.

Implementation: this reuses the classic-bw geometry wholesale (rooms, walls,
doors, features) and only restyles it: its default theme is `blue` (see
`render.theme`), so `renderer "classic-bw" theme blue` draws the same.
"""
from __future__ import annotations

from . import register
from .classic_bw import ClassicBW
from .theme import THEMES

# The blue palette, kept importable under its old names.
_BLUE = THEMES["blue"]
INK, PAGE, FLOOR, GRID = _BLUE.ink, _BLUE.page, _BLUE.floor, _BLUE.map_grid


@register("oldschool-blue")
class OldSchoolBlue(ClassicBW):
    """Classic blue-ink dungeon style: classic-bw geometry, blue theme."""

    default_theme = "blue"
