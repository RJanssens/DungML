"""oldschool-blue — classic blue-ink dungeon-map style.

Blue line-work over a solid blue page, with white room/corridor floors —
the look of the hand-inked blue dungeon maps from early tabletop modules
(and the blue "map symbol" sheets hobbyists still draw today). The negative
space around the explorable area is a flat fill, so the white rooms read as
carved out of solid rock. A `grid_overlay` (if the map declares one) is
tinted blue to match.

Implementation: this reuses the classic-bw geometry wholesale (rooms, walls,
doors, features) and only restyles it. The glyph helpers emit their ink as
the literal colours `#111` (line-work / solid fills) and `#fafafa`
(paper-coloured knockouts) — both inline and via CSS — so rather than thread
an ink colour through ~30 call sites, the context recolours those two tokens
in a single post-pass.
"""
from __future__ import annotations

from ..model import DungeonMap
from . import register
from .classic_bw import ClassicBW, _RenderContext

# Palette — a medium royal blue ink over a solid light-blue page.
INK = "#1b4fa1"          # walls, doors, features, labels
PAGE = "#cfe0f4"         # solid background fill (the "rock" / negative space)
FLOOR = "#ffffff"        # room / corridor floor — white so it pops off the page
GRID = "#a9c4e8"         # graph-paper grid lines

# Ink/paper tokens emitted by the classic-bw glyph helpers, remapped to the
# blue palette in a single pass over the finished SVG. The grid greys are the
# stroke colours baked into the `.map-grid` / `.room-grid` CSS rules, which
# otherwise override the blue group stroke and render the grid grey.
_REMAP = {
    "#111": INK,        # default line-work + solid glyph fills
    "#fafafa": FLOOR,   # paper-coloured knockouts (door gaps, label halos)
    "#9a937f": GRID,    # map-grid overlay lines
    "#b8b3a3": GRID,    # per-room grid lines
}


@register("oldschool-blue")
class OldSchoolBlue(ClassicBW):
    """Classic blue-ink dungeon style: blue line-work, solid fill, grid."""

    def _context_for(self, dmap: DungeonMap) -> "_OldSchoolBlueContext":
        return _OldSchoolBlueContext(dmap)


class _OldSchoolBlueContext(_RenderContext):
    def _bg_default(self) -> str:
        # Solid fill behind everything — white floors are drawn on top, so the
        # exterior reads as solid rock rather than a hatched halo.
        return PAGE

    def _floor_fill(self) -> str:
        return FLOOR

    def _corridor_floor_fill(self) -> str:
        return FLOOR

    def _grid_overlay(self) -> tuple[float | None, str | None]:
        """Honour the map's `grid_overlay` setting (off unless declared), but
        tint it blue when the author didn't pick a colour."""
        spacing, color = super()._grid_overlay()
        if not spacing:
            return None, None
        return spacing, (color or GRID)

    def render(self) -> str:
        svg = super().render()
        for old, new in _REMAP.items():
            svg = svg.replace(old, new)
        return svg
