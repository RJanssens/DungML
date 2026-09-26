"""oldschool-blue — classic blue-ink dungeon-map style.

Blue line-work over a solid blue page, with white room/corridor floors —
the look of the hand-inked blue dungeon maps from early tabletop modules
(and the blue "map symbol" sheets hobbyists still draw today). The negative
space around the explorable area is a flat fill, so the white rooms read as
carved out of solid rock. A `grid_overlay` (if the map declares one) is
tinted blue to match.

Implementation: this reuses the classic-bw geometry wholesale (rooms, walls,
doors, features) and only restyles it: its default theme is `blue` (see
`render.theme`), so `renderer "classic-bw" theme blue` draws the same.
"""
from __future__ import annotations

from ..model import DungeonMap
from . import register
from .classic_bw import ClassicBW, _RenderContext
from .theme import THEMES

# The blue palette, kept importable under its old names.
_BLUE = THEMES["blue"]
INK, PAGE, FLOOR, GRID = _BLUE.ink, _BLUE.page, _BLUE.floor, _BLUE.map_grid


@register("oldschool-blue")
class OldSchoolBlue(ClassicBW):
    """Classic blue-ink dungeon style: classic-bw geometry, blue theme."""

    default_theme = "blue"

    def _context_for(self, dmap: DungeonMap) -> "_OldSchoolBlueContext":
        return _OldSchoolBlueContext(dmap, self._theme_for(dmap))


class _OldSchoolBlueContext(_RenderContext):
    def _grid_overlay(self) -> tuple[float | None, str | None]:
        """Honour the map's `grid_overlay` setting (off unless declared), but
        tint it with the theme's grid colour when the author didn't pick one."""
        spacing, color = super()._grid_overlay()
        if not spacing:
            return None, None
        return spacing, (color or self.MAP_GRID)
