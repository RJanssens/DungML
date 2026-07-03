# Nested `area` in rooms & corridors — design spec

Date: 2026-07-03

## Problem

DungML has a top-level `area` primitive — a decorative terrain shape (water,
lava, pit, …) drawn as a filled polygon but excluded from the connectivity
graph and room numbering. Today an `area` can only be authored at the map body
(or layer) level. Rooms and corridors already accept several *nested*
primitives — `features`, `texts`, `line_features`, and `exits` — authored
inside their block with absolute world coords, **not hoisted**, and pruned by
fog-of-war together with their parent. `area` is the one nested primitive
missing.

We want `area` blocks to be authorable **inside** a room or corridor block, so
that a decorative area (e.g. a pool inside a chamber) is **hidden until its
parent room/corridor is discovered**, matching the established nested-primitive
pattern. A top-level `area` is always visible; a nested one fogs with its room.

## Current state

- `model.py`: `Area` is a top-level primitive held in `DungeonMap.areas` and
  `Layer.areas`. `Room` and `Corridor` carry `features`, `texts`,
  `line_features`, `exits` (nested, absolute coords, not hoisted) but **no**
  `areas` field.
- `grammar.lark`: `room_property` and `corridor_property` accept
  `text_annotation | line_feature` (among others) but **not** `area`. The
  `area` rule exists and is referenced by the map body and `layer_item`.
- `render/classic_bw.py`: `_all_areas()` collects `dmap.areas + layer.areas`.
  Areas are drawn **above room floors but below walls/corridors/features/labels**
  (a deliberate "ground cover" z-order). `OldSchoolBlue(ClassicBW)` inherits
  this, so one change covers both renderers. Compare `_all_line_features()`,
  which already collects `dmap` + layer + **room** + **corridor** line features.
- `graph.fog_of_war()`: prunes `out.rooms`/`out.corridors` to the discovered
  subset via `model_copy(deep=True)`; nested items ride along with each Room
  object. Top-level `areas` are **not** pruned (always shown).
- Web preview is **server-rendered** (SvgPreview injects backend SVG);
  `dmapLanguage.ts` is a Monaco tokenizer that already lists `area` as a
  keyword; `draw.ts` is a click-to-draw tool that emits top-level `area` source.

## Decisions

- **Nest with fog behavior.** A nested `area` renders only when its parent
  room/corridor is visible; fog-of-war prunes it with the parent. This is the
  whole point of nesting vs. a top-level area.
- **Absolute coords, not hoisted** — identical to `Room.texts`/`line_features`.
- **Skip the overlap warning.** A nested decorative area legitimately overlaps
  its parent room; nested areas are excluded from the interior-overlap
  validation warning, the same treatment top-level decorative areas get.
- **No per-area `secret` flag** (YAGNI). Fog-pruning-with-room already hides a
  nested area until discovery. A `secret` flag (hide even in a *discovered*
  room, GM view still shows it) is a possible later extension, not this change.
- **No web or draw-tool change.** Server-rendered preview picks it up; Monaco
  already highlights `area`. The draw tool keeps emitting top-level `area`.

## Design

### 1. Model (`packages/dsl/src/dungml/model.py`)

Add to both `Room` and `Corridor`:

```python
# Decorative areas (pools, pits, lava, …) authored inside this block
# (absolute world coords). NOT hoisted — render only when the room/corridor
# is visible, like texts/line_features; fog prunes them with the parent.
areas: list[Area] = Field(default_factory=list)
```

`Area` is defined later in the module; this is a forward reference resolved the
same way `Room.exits` / `Room.texts` / `Room.line_features` already are (the
module uses `from __future__ import annotations`).

### 2. Grammar (`packages/dsl/src/dungml/grammar.lark`)

Add `area` as an alternative in `room_property` (~line 174) and
`corridor_property` (~line 261), alongside the existing `text_annotation` /
`line_feature`. The `area` rule and `area_property` grammar are unchanged.

### 3. Parser (`packages/dsl/src/dungml/parser.py`)

When building a `Room` / `Corridor`, collect nested `area` nodes into the new
`areas` field, mirroring exactly how nested `line_features` / `texts` are
gathered from the block's properties.

### 4. Renderer (`packages/dsl/src/dungml/render/classic_bw.py`)

Extend `_all_areas()` to also include room- and corridor-nested areas:

```python
def _all_areas(self) -> list[Area]:
    areas: list[Area] = list(self.dmap.areas)
    for layer in self.dmap.layers:
        areas.extend(layer.areas)
    for r in self.dmap.rooms.values():
        areas.extend(r.areas)
    for c in self.dmap.corridors.values():
        areas.extend(c.areas)
    return areas
```

This mirrors `_all_line_features()`. Z-order (ground cover above floors, below
walls/features) and both renderers (`OldSchoolBlue` inherits) are handled for
free. `_all_areas()` is used at every point that currently draws/clips areas,
so nested areas flow through all of them.

### 5. Validation (`packages/dsl/src/dungml/validate.py`)

Run nested areas through the same per-area checks top-level areas get
(degenerate polygon → error, unknown `kind` → error). Iterate `room.areas` and
`corridor.areas` in addition to `dmap.areas` / `layer.areas`. Nested areas are
**not** added to the interior-overlap area set, so they raise no spurious
overlap warning against their parent.

### 6. Fog — no change

`fog_of_war` already prunes rooms/corridors and carries nested fields with each
Room object; a discovered room renders its areas, an undiscovered room drops
them. Verified by test rather than code change.

## Testing

- **Parser** (`packages/dsl/tests`): `area "pool" water { rect … }` inside a
  `room { … }` block parses onto `Room.areas` (and the corridor analogue onto
  `Corridor.areas`); a top-level `area` still lands on `DungeonMap.areas`.
- **Renderer**: a nested area appears in the rendered SVG (its `areas` group /
  fill is present), and renders above the parent room's floor fill.
- **Fog**: with the parent room undiscovered, the nested area is absent from the
  fogged SVG; once discovered, it is present. (A top-level area stays present
  in both, confirming the nested-vs-top-level distinction.)
- **Validation**: an unknown `kind` on a nested area raises the same error as a
  top-level one; a nested area inside its room raises **no** overlap warning.

## Out of scope

- Per-area `secret` flag.
- `draw.ts` emitting areas directly inside a room block (authoring convenience).
- Any web/Monaco change (server-rendered; `area` already a known keyword).
