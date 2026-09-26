"""Themes — the palette and font a renderer draws with.

A renderer is geometry (how walls, corridors, doors and the hatched halo are
built) plus a default theme. The map's `theme NAME` swaps the theme without
touching the geometry, so `renderer "hatched" theme blue` is blue ink on a
hatched halo.

Semantic colours (marker tags, area kinds, slice kinds, the party-start and
exit accents) are *not* theme tokens: they mean something, and stay fixed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Theme:
    name: str
    ink: str = "#111"  # walls, doors, glyph line-work, label text
    floor: str = "#fafafa"  # room floors; also paper knockouts and label halos
    corridor_floor: Optional[str] = None  # None = same as `floor`
    page: str = "#ffffff"  # everything outside the explorable space
    map_grid: str = "#9a937f"  # map-wide graph-paper grid
    room_grid: str = "#b8b3a3"  # per-room / cell grid
    hatch_ink: Optional[str] = None  # hatched halo lines; None = `ink`
    font: str = "Georgia,serif"

    @property
    def corridor(self) -> str:
        return self.corridor_floor or self.floor

    @property
    def hatch(self) -> str:
        return self.hatch_ink or self.ink


PAPER = "#fdfaf3"

THEMES: dict[str, Theme] = {
    t.name: t
    for t in (
        # Black line-work on white — the technical-drawing look.
        Theme("mono"),
        # Warm paper throughout, sepia hatching — the inked-module look.
        Theme("paper", floor=PAPER, page=PAPER, hatch_ink="#2b2418"),
        # Blue ink, white floors on a solid light-blue page.
        Theme(
            "blue", ink="#1b4fa1", floor="#ffffff", page="#cfe0f4",
            map_grid="#a9c4e8", room_grid="#a9c4e8",
        ),
    )
}


def get_theme(name: Optional[str]) -> Optional[Theme]:
    return THEMES.get(name) if name else None


def list_themes() -> list[str]:
    return sorted(THEMES)
