"""The one definition of "what is in this map".

A map's contents live in three kinds of place: the top level, `layer`
blocks (some `hidden` — GM-only), and room/corridor blocks (features, texts,
areas, line features and exits authored inside a node ride with that node).
Everything that needs "all the doors" or "every visible text" goes through
here, so the rules are decided once:

- Named kinds (rooms, corridors, slices) are deduplicated by name, first
  definition wins, top level before layers in source order. (The validator
  warns about the duplicates this hides.)
- `visible=True` drops hidden layers — and with them, anything nested in a
  room or corridor that a hidden layer declares.
- Freestanding members (top level, then each layer) come before nested ones
  (in rooms, then corridors); `nested_first=True` flips that for callers
  whose draw order depends on it.

Pure functions over the parsed model; nothing is copied.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, Union

from .model import Corridor, DungeonMap, Layer, Room

Kind = Literal[
    "rooms", "corridors", "slices",
    "doors", "windows", "markers",
    "features", "texts", "areas", "line_features", "exits",
]

_NAMED = ("rooms", "corridors", "slices")
# Kinds a room/corridor block can also hold.
_NESTABLE = ("features", "texts", "areas", "line_features", "exits")


@dataclass(frozen=True)
class Placed:
    """One member and where it was declared."""

    item: Any
    layer: Optional[Layer] = None  # None = the top level
    host: Optional[Union[Room, Corridor]] = None  # set for nested members

    @property
    def hidden(self) -> bool:
        return self.layer is not None and self.layer.hidden


def _top(dmap: DungeonMap, kind: str) -> list[Any]:
    value = getattr(dmap, kind)
    return list(value.values()) if isinstance(value, dict) else list(value)


def members(
    dmap: DungeonMap,
    kind: Kind,
    *,
    visible: bool = False,
    nested_first: bool = False,
) -> list[Placed]:
    """Every `kind` member of the map, with where each was declared."""
    free: list[Placed] = [Placed(x) for x in _top(dmap, kind)]
    for layer in dmap.layers:
        if visible and layer.hidden:
            continue
        free.extend(Placed(x, layer) for x in getattr(layer, kind))

    if kind in _NAMED:
        seen: dict[str, Placed] = {}
        for p in free:
            seen.setdefault(p.item.name, p)
        return list(seen.values())
    if kind not in _NESTABLE:
        return free

    nested: list[Placed] = []
    for host_kind in ("rooms", "corridors"):
        for h in members(dmap, host_kind, visible=visible):
            nested.extend(Placed(x, h.layer, h.item) for x in getattr(h.item, kind))
    return nested + free if nested_first else free + nested


def nodes(dmap: DungeonMap, *, visible: bool = False) -> dict[str, Union[Room, Corridor]]:
    """Graph-node id (`room.NAME` / `corridor.NAME`) → the room or corridor."""
    out: dict[str, Union[Room, Corridor]] = {}
    for p in members(dmap, "rooms", visible=visible):
        out[f"room.{p.item.name}"] = p.item
    for p in members(dmap, "corridors", visible=visible):
        out[f"corridor.{p.item.name}"] = p.item
    return out


def rooms(dmap: DungeonMap, *, visible: bool = False) -> dict[str, Room]:
    return {p.item.name: p.item for p in members(dmap, "rooms", visible=visible)}


def corridors(dmap: DungeonMap, *, visible: bool = False) -> dict[str, Corridor]:
    return {p.item.name: p.item for p in members(dmap, "corridors", visible=visible)}
