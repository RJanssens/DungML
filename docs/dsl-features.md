# Features & glyphs

Part of the [dungml DSL reference](/docs/dsl).

A **feature** is a piece of map dressing — furniture, a trap, a statue,
a flight of stairs. You place one with a `feature` instance, and you
describe what it looks like with a `feature_def`. Built-in features live
in the bundled `core.dmap` library; bring them in with
`include "core.dmap"`.

A `feature_def` is drawn in one of two ways:

- **`shape`** (+ `overlay`s) — a filled, coloured shape. Good for tokens
  and dressing where a solid blob of colour reads well.
- **`glyph`** — ordered line-art draw commands (the vocabulary the
  built-in features use). Good for crisp black-on-white map symbols.

A def uses exactly one of the two.

---

## `feature_def` — defining a feature

### Filled-shape form

```dmap
feature_def "runestone" {
  name "Runestone"
  shape circle radius 0.6
  background "#1a1530"
  outline { color "#c9a227" width 0.08 stroke dashed }
  overlay circle radius 0.25 fill "#c9a227"
  description "A flat-topped basalt stone. Runes glow when touched."
}
```

| Property      | Required | Notes |
|---------------|----------|-------|
| `shape`       | one of `shape`/`glyph` | A shape primitive (below) |
| `glyph`       | one of `shape`/`glyph` | A block of draw commands (below) |
| `name STR`    | no       | Human-readable display name (otherwise the id is used) |
| `background`  | no       | Fill color for `shape` (hex or CSS color name) |
| `outline`     | no       | See below; applies to `shape` |
| `overlay`     | repeat   | Layered shapes drawn on top of the background |
| `description` | no       | Long-form description (shown by the print view) |

#### Shape primitives

```dmap
shape circle radius 0.6
shape rect   2 x 1.2
shape polygon (0,0) (1,0) (1,1) (0.5,1.5) (0,1)
```

A polygon needs at least three points. Shape `rect` is centred on the
instance origin (width × height).

#### `outline { ... }`

```dmap
outline {
  color  "#1a1a1a"
  width  0.08           # in world units
  stroke solid          # solid | dashed | dotted
}
```

#### `overlay`

```dmap
overlay circle radius 0.25 fill "#c9a227"
overlay rect 1.6 x 0.6 offset 0,0 fill "#888888"
```

An overlay is a smaller shape (same primitives as `shape`) painted on
top of the background, optionally offset relative to the instance
center. `offset` defaults to `0,0`.

---

## `glyph` — line-art draw commands

A `glyph` block is an ordered list of primitives drawn in the feature's
local coordinate frame (origin at the instance point, +x right). Each
command is:

```
<primitive> <role> <geometry> <style*>
```

```dmap
feature_def "ward_rune" {
  glyph {
    circle  stroke at 0,0 radius 0.35
    polygon fill   (0,-0.2) (0.2,0.1) (-0.2,0.1)
    path    stroke "M-0.2,0 Q0,-0.25 0.2,0" fill-color "none"
    line    stroke from -0.3,0.18 to 0.3,0.18 stroke-width 0.1
  }
}
```

### Primitives

| Primitive  | Geometry |
|------------|----------|
| `circle`   | `at CX,CY radius R` |
| `rect`     | `at X,Y W x H` — `X,Y` is the **top-left corner** (SVG-style), optional `rx R` rounding |
| `line`     | `from X1,Y1 to X2,Y2` |
| `polygon`  | `(x,y) (x,y) …` — at least 3 points, implicitly closed |
| `polyline` | `(x,y) (x,y) …` — an open run of points (use `fill-color "none"`) |
| `path`     | `"<svg path data>"` — a raw SVG `d` string |

### Role

The role selects the styling class:

| Role     | Renders as | Effect |
|----------|------------|--------|
| `stroke` | `class="feature"` | white fill, black outline (the default for outlined symbols) |
| `fill`   | `class="feature-fill"` | solid black, no stroke |
| `plain`  | no class | unstyled — control it entirely with the overrides below |

Open shapes (`polyline`, curved `path`) drawn with the `stroke` role
should set `fill-color "none"` so the curve isn't filled.

### Style overrides

Optional, appear after the geometry, in any order:

| Override            | Meaning |
|---------------------|---------|
| `fill-color "C"`    | explicit fill colour, or `"none"` |
| `stroke-color "C"`  | explicit stroke colour, or `"none"` |
| `stroke-width N`    | stroke width in world units |
| `rx N`              | corner radius (`rect` only) |
| `class "NAME"`      | append an extra CSS class alongside the role class |

Because glyphs use the shared `feature` / `feature-fill` classes, they
recolour correctly under palette-swapping renderers like
`oldschool-blue`.

---

## `feature` instance

```dmap
feature hearth      at 9,4
feature "runestone" at 11,35
feature altar       at 12,11 scale 1.3 rotate 90 {
  description "Offerings expected of visiting scholars."
}
```

- The feature reference is either a `CNAME` (e.g. `hearth`) or a quoted
  string (for ids that contain hyphens, e.g. `"pit-trap"`).
- `at X,Y` is required.
- `rotate N` (degrees) and `scale N` (multiplier) are optional.
- An optional `{ description "..." }` block attaches an instance-level
  description, overriding the `feature_def` description for this
  particular instance.

Features may be placed inside a `room`, inside a `layer`, or at the top
level of the file. They are visual dressing only — they do not
participate in the [connectivity graph](/docs/dsl-tooling).

---

## The `core.dmap` built-in library

`include "core.dmap"` brings in every built-in feature below as a
`glyph` `feature_def`. Built-ins are **not** implicit — without the
include, a `feature pillar` is an unknown-feature error. A local
`feature_def` (or an earlier include) with the same id wins, so you can
override any built-in's rendering.

The authoritative definitions live in
`packages/dsl/src/dungml/includes/core.dmap` — read or copy them as a
starting point for your own glyphs.

### Glyph index

Thirty-two built-in features (two are aliases):

#### Obstacles & traps

| Name | Glyph |
|------|-------|
| `pillar` | small solid dot — a column |
| `rubble` | three scattered debris polygons |
| `portcullis` | three solid dots in a row |
| `pit-trap` (alias `trap`) | circle with an X |
| `dart-trap` | circle with a dart/arrow across it |
| `fire-trap` | circle with a flame |

#### Furniture & fittings

| Name | Glyph |
|------|-------|
| `chest` | rectangle with a lid line |
| `altar` | rectangle with a small cross |
| `fountain` | circle with two wave lines |
| `water` | pale-filled rectangle with ripples |
| `brazier` | circle with a flame |
| `statue` | solid disc with a white star |
| `marker` | small solid dot |

#### Stairs

| Name | Glyph |
|------|-------|
| `stairs-up` | treads with an up arrow |
| `stairs-down` | treads with a down arrow |
| `stairs-left` | treads with a left arrow |
| `stairs-right` | treads with a right arrow |
| `stairs-spiral` (alias `spiral-stairs`) | spiral with radial steps and a newel post |

#### Building / domestic

| Name | Glyph |
|------|-------|
| `hearth` | rectangle with a flame |
| `stove` | rectangle with four burner rings |
| `table` | plain rectangle |
| `chair` | small rectangle with a thick back edge |
| `bed` | rectangle with a pillow rectangle |
| `desk` | rectangle with a drawer line |
| `bookshelf` | rectangle with vertical dividers |
| `bath` | rounded rectangle |
| `wardrobe` | rectangle with a centre split |
| `barrel` | circle with a band line |
| `crate` | rectangle with an X |

#### Terrain

| Name | Glyph |
|------|-------|
| `bridge` | wood deck with rails and plank ticks — place on top of a `slice` (rotate to align, scale to the slice width) |

### `common-dungeon.dmap`

A second bundled library of filled-shape dressing (not glyphs):
`magic_circle`, `sarcophagus`, `runestone`, `arcane_pillar`,
`bookcase_tall`, `water_pool`, `sarcophagus_grand`, `spike_trap`,
`ritual_brazier`, `obelisk`. Bring it in with
`include "common-dungeon.dmap"`.
