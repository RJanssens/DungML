# Language reference

A keyword-by-keyword reference for the dungml DSL. Every keyword that can
appear in a `.dmap` file is listed here with the elements it may contain,
a short description, and an example.

For prose walkthroughs see the topic guides:
**[Map header](/docs/dsl-map)**, **[Geometry](/docs/dsl-geometry)**,
**[Features & glyphs](/docs/dsl-features)**, **[Validation & tooling](/docs/dsl-tooling)**.
The authoritative grammar lives at `packages/dsl/src/dungml/grammar.lark`
and the typed model at `packages/dsl/src/dungml/model.py`.

## How to read this reference

Each entry gives:

- **Context** — where the keyword may legally appear (which parent block,
  or *top level* for a standalone declaration).
- **Children** — the properties / nested elements it accepts. Order never
  matters; every child is optional unless marked *required*.
- An **example** in `dmap`.

Syntax conventions: `STRING` is a double-quoted string, `NUMBER` an
integer or decimal (optionally negative), `NAME` a bare identifier
(`[a-zA-Z_][a-zA-Z0-9_-]*`), and `REF` a dotted reference such as
`room.kitchen` or `corridor.south_passage`. Coordinates are written
`x,y` (no spaces) in world units.

---

## Top-level declarations

These may appear at the top level of a file, in any order. Exactly one
`map` (or one `scenario`) is required; everything else is optional and
may repeat.

| Keyword | Cardinality | Purpose |
|---------|-------------|---------|
| `map` | exactly 1 (or one `scenario`) | Bounds, grid, renderer choice |
| `scenario` | alternative to `map` | Multi-map adventure bundle |
| `include` | any | Pull in another `.dmap` library |
| `feature_def` | any | Define reusable furniture / dressing |
| `room` | any | Walled spaces |
| `corridor` | any | Connecting passages |
| `slice` | any | Cross-cutting terrain (river / ravine / split) |
| `door` | any | Openings on walls |
| `window` | any | Window slits on walls |
| `marker` | any | Dynamic tokens (party, NPCs, monsters) |
| `text` | any | Freestanding map text |
| `area` | any | Decorative terrain pools |
| `line_feature` | any | Styled polyline decoration |
| `exit` | any | Cross-map transition |
| `layer` | any | Logical group, optionally hidden |
| `feature` | any | Place a defined feature (also nests in rooms) |

---

## `include`

Pull every top-level declaration from another `.dmap` file into this one —
typically a `feature_def` library. Local declarations and earlier includes
win on name collision, so you can shadow any included feature.

**Context:** top level.
**Children:** none (takes a single `STRING` path).

```dmap
include "core.dmap"            # the built-in feature library
include "common-dungeon.dmap"  # extra dungeon dressing
```

---

## `scenario`

An adventure-level bundle: scenario-wide prose plus references to the
`.dmap` files it spans. Use *instead of* a top-level `map`. The scenario
renderer pulls in each referenced map.

**Context:** top level (mutually exclusive with `map`).

| Child | Description |
|-------|-------------|
| `map STRING` | A path reference to a `.dmap` file in the scenario. Repeatable. |
| `description` | Scenario-wide read-aloud / summary text. |
| `dm_notes` | Scenario-wide GM-only notes. |

```dmap
scenario "The Sunless Citadel" {
  description "A fallen fortress swallowed by a ravine."
  map "maps/overgrown-courtyard.dmap"
  map "maps/goblin-warren.dmap"
}
```

---

## `map`

The required map header: declares the canvas, the renderer, and map-wide
display options.

**Context:** top level (exactly one).

| Child | Description |
|-------|-------------|
| `grid { … }` | *Required.* Cell size, units, bounds, origin. See [`grid`](#grid). |
| `renderer STRING` | Renderer id, e.g. `"classic-bw"`, `"floorplan"`. |
| `theme NAME` | Palette + font: `mono`, `paper`, `blue`. Defaults to the renderer's own (see dsl-map). |
| `legend` | Draw a symbol-legend strip below the map. |
| `grid_overlay [NUMBER [STRING]]` | Graph-paper grid across the whole canvas; optional spacing + CSS colour. |
| `cell_grid [NUMBER [STRING]]` | Per-cell grid inside rooms/corridors; optional spacing + colour. |
| `background STRING` | Map-wide background fill (CSS colour or texture id). |
| `party_start NUMBER,NUMBER` | Marker at a world cell. |
| `party_start STRING [at NUMBER,NUMBER]` | Party begins in room/corridor `STRING` (marker at its centroid, or the `at` cell). Becomes a new session's default start node. |
| `room_numbers NAME` | Auto-number rooms (`on` / `off`). |
| `title STRING` | On-map title; accepts `label` modifiers (`at`, `align`, `size`, `rotate`). |
| `corners NAME` | Map-wide default corridor corner style (`round` or `straight`). |
| `description` | Map read-aloud / summary text. |
| `dm_notes` | Map-wide GM-only notes. |

```dmap
map "Miller's Cottage" {
  grid { cell 32 px  units feet 5  bounds 30 x 20 }
  renderer "floorplan"
  legend
  grid_overlay 1 "#444"
  party_start 2,18
}
```

### `grid`

The canvas definition. Required inside `map`.

**Context:** inside `map`.

| Child | Description |
|-------|-------------|
| `cell NUMBER px` | Pixels per world unit when rasterising. |
| `units NAME NUMBER` | Real-world unit name + size per cell, e.g. `units feet 5`. |
| `bounds NUMBER x NUMBER` | Map width × height in world units (inclusive). |
| `origin top-left \| bottom-left` | Y-axis direction; default `top-left`. |

```dmap
grid {
  cell   32 px
  units  feet 5
  bounds 40 x 30
  origin bottom-left
}
```

---

## `room`

A walled space. Exactly one shape is required; everything else is optional.

**Context:** top level, or inside a [`layer`](#layer).

| Child | Description |
|-------|-------------|
| *a shape* | *Required.* One of `rect`, `polygon`, `circle`, `boundary` (below). |
| `label STRING …` | On-map label. See [`label`](#label). |
| `feature …` | Furniture placed in the room. See [`feature`](#feature). |
| `text STRING at X,Y …` | Text bound to the room — only drawn when the room is visible. See [`text`](#text). |
| `exit at X,Y { … }` | A cross-map exit anchored in the room — only drawn when the room is visible. See [`exit`](#exit). |
| `line_feature STRING { … }` | A polyline decoration bound to the room — only drawn when the room is visible. See [`line_feature`](#line_feature). |
| `grid NUMBER [STRING]` | Per-room grid overlay: spacing + optional CSS colour. |
| `background STRING` | Floor fill (CSS colour or texture id, e.g. `"water"`). |
| `line_style NAME [NUMBER]` | Wall edge style: `solid` or `organic` (+ optional waviness). |
| `allow_overlap` | Opt out of the interior-overlap validation warning. |
| `description` | Read-aloud text. |
| `dm_notes` | GM-only notes. |

```dmap
room "kitchen" {
  rect 2,2 8 x 7
  label "Kitchen"
  feature hearth at 9,4 rotate 90
  text "A" at 6,6 description "Bloodstain — see area 4"
  description "Warm, low-ceilinged, smelling of woodsmoke."
}
```

### Room shapes

A room takes exactly one of these.

| Shape | Syntax | Description |
|-------|--------|-------------|
| `rect` | `rect X,Y W x H` | Axis-aligned rectangle from a corner. |
| `polygon` | `polygon (X,Y) (X,Y) …` | Closed polygon from points. |
| `circle` | `circle at X,Y radius R` | Circular room. |
| `boundary` | `boundary { … }` | Mixed straight/arc outline (below). |

```dmap
room "well_chamber" { circle at 12,12 radius 4 }
room "cave"  { polygon (2,2) (9,3) (8,9) (1,7) }
```

### `boundary`

A closed outline mixing straight lines and 3-point arcs. The final edge
implicitly connects back to `start`.

**Context:** inside a `room` (as its shape).

| Child | Description |
|-------|-------------|
| `start X,Y` | *Required first edge.* The opening vertex. |
| `line to X,Y` | A straight edge to a point. |
| `arc to X,Y via X,Y` | An arc ending at a point, bowing through a midpoint. |

```dmap
room "apse" {
  boundary {
    start 0,0
    line to 6,0
    arc  to 6,6 via 8,3
    line to 0,6
  }
}
```

---

## `corridor`

A connecting passage drawn as a centerline with walls. The optional
second `STRING` is a display name (tooltip / legend only — not drawn).
A dead end with no door/exit at it is capped with a flat wall.

**Context:** top level, or inside a [`layer`](#layer).

| Child | Description |
|-------|-------------|
| `width NUMBER` | Corridor width in world units. `width 0` draws a bare centerline (a route marker). |
| `segment line from X,Y to X,Y` | A straight run. See [segments](#segments). |
| `segment arc center X,Y radius R from-angle A to-angle A [sweep cw\|ccw]` | A curved run. |
| `node NAME at X,Y` | A named junction point (used with `run`). |
| `run NAME to NAME` | A straight run between two named nodes (desugars to a segment). |
| `corners NAME` | Corner style at bends: `round` (default) or `straight`. |
| `feature …` | Furniture on the corridor (e.g. a portcullis). |
| `text STRING at X,Y …` | Text bound to the corridor — only drawn when it is visible. |
| `exit at X,Y { … }` | A cross-map exit anchored in the corridor — only drawn when it is visible. |
| `line_feature STRING { … }` | A polyline decoration bound to the corridor — only drawn when it is visible. |
| `label STRING …` | An on-map label drawn over the corridor. |
| `background STRING` | Floor fill override. |
| `line_style NAME [NUMBER]` | Wall edge style. |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
corridor "south_passage" "Servants' Run" {
  width 2
  segment line from 14,9 to 24,9
  segment line from 24,9 to 24,4
  corners straight
}
```

### Segments

`segment` accepts one of two geometries. Branches form where ≥3 segments
share an endpoint (T / crossing).

| Segment | Syntax |
|---------|--------|
| `line` | `segment line from X,Y to X,Y` |
| `arc` | `segment arc center X,Y radius R from-angle A to-angle A [sweep cw\|ccw]` |

```dmap
corridor "bend" {
  width 1.5
  node a at 4,4
  node b at 4,12
  node c at 14,12
  run a to b
  run b to c
}
```

---

## `slice`

Cross-cutting terrain (rivers, ravines, splits): the same line/arc segment
geometry as a corridor, but rendered as an impassable terrain band rather
than a passable interior. Bridges are regular `feature`s placed on top.

**Context:** top level, or inside a [`layer`](#layer).

| Child | Description |
|-------|-------------|
| `kind river \| ravine \| split` | The terrain band style. |
| `width NUMBER` | Band width in world units. |
| `segment …` | Line/arc geometry (same as a corridor). |
| `label STRING …` | On-map label. |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
slice "the_rift" {
  kind ravine
  width 3
  segment line from 0,10 to 30,12
}
```

---

## `door`

An opening on a wall, and a connector in the connectivity graph. Its
position is projected onto the nearest wall.

**Context:** top level, or inside a [`layer`](#layer).

| Child | Description |
|-------|-------------|
| `connects REF[, REF]` | One or two `room.NAME` / `corridor.NAME` refs. Recommended (validation warns when absent). |
| `type NAME` | `wooden` (default), `iron`, `stone`, `secret`, `concealed`, `smashed`, `arch`, `portcullis`, `open`, `double`, `one-way`. |
| `state NAME` | `closed` (default), `open`, `locked`. |
| `facing NAME` | `north` / `south` / `east` / `west`; hints the leaf side and sets the `one-way` direction. |
| `width NUMBER` | Opening width; default `1.0`. |
| `trapped` | Flag the door as trapped (GM-only; hidden in the fogged view). |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
door at 15,2 {
  connects room.parlor, corridor.hall
  type wooden
  state locked
  facing south
  trapped
}
```

---

## `window`

A window slit on a wall. Like a door, the position is projected onto the
nearest wall of the named node.

**Context:** top level, or inside a [`layer`](#layer).

| Child | Description |
|-------|-------------|
| `in REF` | *Required.* The `room.NAME` / `corridor.NAME` the window sits on. |
| `width NUMBER` | Slit width; default `1.0`. |
| `description` | Optional free text. |

```dmap
window at 4,9 { in room.entry_atrium width 1.5 }
```

---

## `marker`

A lightweight named token (party member, NPC, monster) at a single point.
Unlike `feature` (static furniture), markers represent *who is here now*.
Modifiers may appear in any order.

**Context:** top level, or inside a [`layer`](#layer).

| Child | Description |
|-------|-------------|
| `at X,Y` | *Required.* Token position. |
| `tag NAME \| STRING` | Palette key (`party`, `ally`, `npc`, `enemy`, `boss`, `neutral`, `unknown`) or a CSS colour literal. Default `neutral`. |
| `label STRING` | Caption rendered below the token. |
| `initial STRING` | 1–2 char glyph in the disc; defaults to the name's first char. |
| `size NUMBER` | Token radius; default `0.5`. |
| `in REF` | Optional `room.NAME` / `corridor.NAME` location. |
| `image STRING` | Portrait path/URL clipped to the token circle. |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
marker "Aragorn" at 5,5 tag party initial "A"
marker "Goblin Boss" at 20,4 tag boss label "Broken-Tooth" size 0.6 in room.guardroom
```

---

## `text`

Freestanding map text. At the top level (or in a `layer`) it is always-on
decoration; nested inside a `room`/`corridor` it is bound to that node and
drawn only when the node is visible (fog prunes them together). Accepts an
inline modifier list **or** a braced block — they are interchangeable.

**Context:** top level, inside a [`layer`](#layer), or inside a `room` / `corridor`.

| Child | Description |
|-------|-------------|
| `at X,Y` | *Required.* Anchor position (absolute world coords, even when nested). |
| `size NUMBER` | Multiplier on the base label size; default `1.0`. |
| `rotate NUMBER` | Rotation in degrees. |
| `description` | Meaning of the glyph — surfaced as a hover tooltip / key. |
| `dm_notes` | GM-only note. |

```dmap
text "A" at 6,6 size 1.5 description "Altar of the Old Gods"

text "D" at 12.5,26.5 {
  description "A glyph carved into the wall. Touching it teleports to area 24."
}
```

---

## `area`

Decorative terrain (water / lava / pit / …) drawn as a filled shape. It
reuses the room shape grammar but is **not** a room — no walls, no graph,
no numbering.

**Context:** top level, or inside a [`layer`](#layer).

| Child | Description |
|-------|-------------|
| *a shape* | One of `rect` / `polygon` / `circle` / `boundary`. |
| `kind NAME` | Built-in fill palette (e.g. `water`, `lava`, `pit`). May also follow the name: `area "pool" kind water { … }`. |
| `background STRING` | Override the palette fill. |
| `label STRING …` | On-map label. |
| `line_style NAME [NUMBER]` | Edge style (`organic` for natural pools). |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
area "reflecting_pool" kind water {
  polygon (4,4) (10,4) (10,9) (4,9)
  line_style organic
}
```

---

## `line_feature`

A styled polyline decoration drawn along a path of points: `bars` (dotted),
`curtain` (wavy), `barred`, `step` (two thin parallel lines). Not a
connector — excluded from the graph.

**Context:** top level, inside a [`layer`](#layer), or inside a `room` / `corridor`.
A nested line feature is drawn only when its node is visible (fog prunes them
together).

| Child | Description |
|-------|-------------|
| `kind NAME` | The polyline style. May also sit before the brace: `line_feature "x" kind bars { … }`. |
| `point X,Y` | A vertex along the path. Repeatable. |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
line_feature "portcullis_track" kind bars {
  point 10,4
  point 14,4
}
```

---

## `exit`

A cross-map transition: stepping on it sends the party to a position on
another map in the same project.

**Context:** top level, inside a [`layer`](#layer), or inside a `room` / `corridor`.

| Child | Description |
|-------|-------------|
| `to STRING at X,Y` | *Required.* Target map name and the landing position on it. |
| `label STRING …` | An on-map label. |
| `secret` | Hide from the fogged players' view until discovered. |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
exit at 3,4 {
  to "cellar" at 10,2
  label "Down to the cellar"
  secret
}
```

---

## `feature_def`

Define a reusable feature (furniture / dressing) that `feature` instances
then place. A definition uses *either* a filled `shape` (with optional
`overlay`) *or* a `glyph` of line-art commands.

**Context:** top level.

| Child | Description |
|-------|-------------|
| `shape SHAPE` | A filled base shape: `circle radius R`, `rect W x H`, or `polygon …`. |
| `glyph { … }` | Line-art draw commands (below) — an alternative to `shape`. |
| `outline { … }` | Stroke styling for the shape: `color`, `width`, `stroke`. |
| `overlay SHAPE [offset X,Y] [fill STRING]` | A second shape layered on the base. |
| `background STRING` | Base fill colour / texture. |
| `name STRING` | Human-readable display name. |
| `secret` | Mark the whole feature type GM-only. |
| `description` | Feature description. |

```dmap
feature_def "altar" {
  shape rect 2 x 1
  background "#d8d2c4"
  outline { color "#333" width 0.08 stroke solid }
  overlay circle radius 0.3 offset 0,0 fill "#a33"
}
```

### `glyph`

An ordered list of raw draw primitives. Each begins with a **role**
(`stroke`, `fill`, or `plain`) selecting its CSS class, followed by
geometry, then optional style overrides.

**Context:** inside a `feature_def`.

| Primitive | Syntax |
|-----------|--------|
| `circle` | `circle ROLE at X,Y radius R` |
| `rect` | `rect ROLE at X,Y W x H` |
| `line` | `line ROLE from X,Y to X,Y` |
| `polygon` | `polygon ROLE (X,Y) …` |
| `polyline` | `polyline ROLE (X,Y) …` |
| `path` | `path ROLE STRING` (raw SVG path data) |

Style overrides (after the geometry): `fill-color STRING`,
`stroke-color STRING`, `stroke-width NUMBER`, `rx NUMBER`, `class STRING`.

```dmap
feature_def "chest" {
  glyph {
    rect stroke at -0.5,-0.4 1 x 0.8 stroke-width 0.06
    line stroke from -0.5,0 to 0.5,0
  }
}
```

---

## `feature`

Place a defined feature at a point. Used at the top level, in a `layer`,
or nested in a `room` / `corridor`.

**Context:** top level, inside a [`layer`](#layer), or inside a `room` / `corridor`.

| Element | Description |
|---------|-------------|
| `feature REF at X,Y` | *Required.* The feature id (bare name or quoted) and its position. |
| `rotate NUMBER` | Rotation in degrees. |
| `scale NUMBER[:NUMBER]` | Uniform scale, or independent `X:Y`. |
| `{ … }` (optional block) | `description`, `dm_notes`, and/or `secret` for this instance. |

```dmap
feature hearth at 9,4 rotate 90
feature "stairs-up" at 12,2 scale 1.5

feature pit at 7,7 {
  secret
  dm_notes "Falls 20ft into area 12."
}
```

---

## `layer`

A logical grouping of declarations, optionally `hidden`. A hidden layer is
parsed and validated but skipped by the renderer — useful for DM-only
content or alternate states.

**Context:** top level.

| Child | Description |
|-------|-------------|
| `hidden` | (After the name.) Exclude the layer's contents from rendering. |
| *contents* | Any of: `room`, `corridor`, `slice`, `door`, `window`, `marker`, `text`, `area`, `line_feature`, `exit`, `feature`. |

```dmap
layer "gm_only" hidden {
  marker "Ambush" at 14,8 tag enemy
  text "trap here" at 14,9 description "Pressure plate"
}
```

---

## Shared properties

These appear inside several blocks (noted in each entry above).

### `label`

An on-map text label. Used by `room`, `corridor`, `slice`, `area`, and the
map `title`.

| Modifier | Description |
|----------|-------------|
| `at X,Y` | Absolute position. |
| `align ALIGN_V ALIGN_H` | Anchor within the parent: vertical `top`/`middle`/`bottom`, horizontal `left`/`center`/`right`. |
| `size NUMBER` | Size multiplier. |
| `rotate NUMBER` | Rotation in degrees. |

```dmap
label "Great Hall" align top center size 1.4
```

### `description`

Read-aloud / summary text. Accepts a normal string or a triple-quoted
(`"""`) multi-line string. Surfaced via `data-description`.

```dmap
description """
The pride of Cael Voren. Vaulted ceiling lost to gloom.
"""
```

### `dm_notes`

GM-only text (traps, secrets, hooks). Same string forms as `description`;
surfaced via `data-dm-notes` and stripped from the fogged players' view.

```dmap
dm_notes "The third flagstone triggers a dart trap (DC 14)."
```

### `secret`

A bare flag marking an element GM-only: drawn in the full GM view, stripped
from the fogged players' view until discovered. Valid on a `feature_def`, a
`feature` instance (inside its block), and an `exit`.

```dmap
exit at 3,4 { to "vault" at 2,2  secret }
```
