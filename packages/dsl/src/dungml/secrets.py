"""GM-only content the DM can reveal during play.

`secret` marks anything the players shouldn't see until the DM shows it:
features (a feature type can be secret by default — core.dmap's traps
are), texts, areas, line features, markers and cross-map exits. The players'
view (`graph.fog_of_war`) hides each one until its key is in the play
session's reveal list.

A secret's key is its `id` when the author gave one (`feature pit-trap at
3,3 id pit_1`), else where it sits: `room.crypt/feature@3,3`,
`map/marker:lurker`, `layer.L/area:sinkhole`. An id survives the author
nudging the thing around; a position key doesn't — the same trade-off as
door keys.

Hidden layers are not secrets: they are wholly GM-only and never drawn for
the players, so nothing in them is revealable.

This module is the one definition of "what is revealable, under which key":
fog_of_war, room_context and the session routes all use it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from . import walk
from .geometry import owner_node, room_polygon
from .graph import _fmt
from .model import DungeonMap, Room, Vec2
from .walk import Placed

# walk kind → the short word used in keys and responses.
_KINDS = {
    "features": "feature",
    "texts": "text",
    "areas": "area",
    "line_features": "line_feature",
    "markers": "marker",
    "exits": "exit",
}


@dataclass(frozen=True)
class Secret:
    key: str
    kind: str  # feature | text | area | line_feature | marker | exit
    label: str  # something a DM can read: the feature type, the text, the name
    node: Optional[str]  # the room/corridor it is in, if any
    item: Any


def is_secret(dmap: DungeonMap, kind: str, item: Any) -> bool:
    """Is this member GM-only? Features are secret by instance or by type."""
    if kind == "features":
        fd = dmap.feature_defs.get(item.ref)
        return bool(item.secret or (fd is not None and fd.secret))
    return bool(getattr(item, "secret", False))


def secret_key(kind: str, item: Any, scope: str) -> str:
    """The reveal key for one member (see the module docstring)."""
    ident = getattr(item, "id", None)
    if ident:
        return ident
    word = _KINDS[kind]
    if kind in ("areas", "line_features", "markers"):
        short = {"areas": "area", "line_features": "line", "markers": "marker"}[kind]
        return f"{scope}/{short}:{item.name}"
    x, y = item.position
    return f"{scope}/{word}@{_fmt(x)},{_fmt(y)}"


def scope_of(dmap: DungeonMap, p: Placed) -> str:
    """`room.X` / `corridor.Y` for nested members, else `layer.L` or `map`."""
    if p.host is not None:
        is_room = any(r is p.host for r in walk.rooms(dmap).values())
        return f"{'room' if is_room else 'corridor'}.{p.host.name}"
    return f"layer.{p.layer.name}" if p.layer is not None else "map"


def _anchor_point(kind: str, item: Any) -> Optional[Vec2]:
    """A point that says where a freestanding member is, for owner lookup."""
    if kind == "areas":
        poly = room_polygon(Room(name=item.name, shape=item.shape))
        return (sum(x for x, _ in poly) / len(poly), sum(y for _, y in poly) / len(poly))
    if kind == "line_features":
        return item.points[0] if item.points else None
    return getattr(item, "position", None)


def _label(kind: str, item: Any) -> str:
    if kind == "features":
        return item.ref
    if kind == "texts":
        return item.text
    if kind == "exits":
        return item.label.text if item.label is not None else f"exit to {item.target_map}"
    return item.name


def list_secrets(dmap: DungeonMap) -> list[Secret]:
    """Every revealable secret, in source-walk order (hidden layers excluded)."""
    out: list[Secret] = []
    for kind, word in _KINDS.items():
        for p in walk.members(dmap, kind, visible=True):
            if not is_secret(dmap, kind, p.item):
                continue
            scope = scope_of(dmap, p)
            if p.host is not None:
                node: Optional[str] = scope
            elif getattr(p.item, "location", None):
                node = p.item.location  # a marker pinned to a node
            else:
                pos = _anchor_point(kind, p.item)
                node = owner_node(dmap, pos) if pos is not None else None
            out.append(Secret(
                key=secret_key(kind, p.item, scope), kind=word,
                label=_label(kind, p.item), node=node, item=p.item,
            ))
    return out
