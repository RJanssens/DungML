# The dungml DSL

A `.dmap` file describes a single tabletop map — a building, a dungeon
level, an outdoor encounter site — in a small, declarative language.
The parser turns text into a typed semantic model; one of the bundled
renderers turns that model into SVG.

This is the index of the DSL reference. The material is split into
focused sections (links open in a new tab):

- **[Map header](/docs/dsl-map)** — the required `map` block, grid,
  renderer, theme, grid overlay.
- **[Features & glyphs](/docs/dsl-features)** — `feature_def`, the
  `glyph` drawing primitives, feature instances, the bundled `core.dmap`
  library, and the **glyph index**.
- **[Geometry](/docs/dsl-geometry)** — `room`, `corridor`, `slice`,
  `door`, `window`, `marker`, `layer`.
- **[Validation & tooling](/docs/dsl-tooling)** — semantic checks, the
  connectivity graph, the MCP authoring/play-session tools, the CLI,
  and a worked example.

---

## At a glance

```dmap
include "core.dmap"          # built-in feature library (hearth, table, …)

map "Miller's Cottage" {
  grid {
    cell   32 px
    units  feet 5
    bounds 30 x 20
  }
  renderer "floorplan"
}

room "kitchen" {
  rect 2,2 8 x 7
  label "Kitchen"
  feature hearth at 9,4 rotate 90
  feature table  at 6,6
}

door at 15,2 {
  connects room.kitchen
  type wooden
  state closed
  facing south
}

window at 4,2 { in room.kitchen width 1 }
```

A `.dmap` file is a flat sequence of top-level declarations. Order does
not matter — declarations are collected, then validated and rendered.

The grammar lives at `packages/dsl/src/dungml/grammar.lark`. The
semantic model lives at `packages/dsl/src/dungml/model.py`.

---

## File structure

A file is any number of top-level declarations in any order:

| Declaration   | Cardinality | Purpose |
|---------------|-------------|---------|
| `map`         | exactly 1   | Bounds, grid, renderer choice |
| `feature_def` | any         | Reusable furniture / dressing |
| `room`        | any         | Walled spaces with features |
| `corridor`    | any         | Connecting passages |
| `door`        | any         | Openings on walls |
| `window`      | any         | Window slits on exterior walls |
| `layer`       | any         | Logical group, optionally hidden |
| `include`     | any         | Pull in another `.dmap` library |

### Comments

Comments start with `#` and run to end of line:

```dmap
# This is a comment.
room "vault" { rect 0,0 5 x 5 }  # trailing comments are fine too
```

### Strings

Strings use double quotes. `\n`, `\t`, `\r`, `\"`, and `\\` are
honored. Multi-line strings use Python-style triple quotes (`"""`)
and trim a single leading and trailing newline:

```dmap
description """
The pride of Cael Voren. Vaulted ceiling lost to gloom;
book-spines reach higher than the eye can follow.
"""
```

### Numbers and coordinates

Numbers are integers or decimals, optionally negative. Coordinates are
written as `x,y` (no spaces inside the pair) in **world units** —
typically the same unit declared in `grid { units ... }`. The origin
is `top-left` by default; pass `origin bottom-left` to flip the Y
axis. Bounds are inclusive: a position of `(0,0)` and `(bounds_w,
bounds_h)` are both legal.

### Identifiers and references

`CNAME` identifiers match `[a-zA-Z_][a-zA-Z0-9_-]*`. References use
dotted form: `room.kitchen`, `corridor.south_passage`. The kind prefix
(`room` / `corridor`) is required.

---

## `include` — pulling in another file

```dmap
include "core.dmap"            # the built-in feature library
include "common-dungeon.dmap"  # extra dungeon dressing
```

`include` brings in a library of `feature_def`s (or any other top-level
declarations) from another file. Includes are resolved by name against
(1) the including file's directory, (2) the bundled library shipped with
the parser, and (3) the raw path. Local declarations — and earlier
includes — win on name collision, so you can shadow any included feature
without editing the library. This is the supported way to **toggle an
alternate rendering** of a feature: define it locally, or include a
template that redefines it.

Two libraries ship with dungml:

- **`core.dmap`** — the built-in feature library (`pillar`, `chest`,
  `stairs-up`, `bridge`, `hearth`, …). Built-in features are *not*
  implicit: a map must `include "core.dmap"` to use them. See
  **[Features & glyphs](/docs/dsl-features)** for the full list.
- **`common-dungeon.dmap`** — extra dressing as filled-shape
  `feature_def`s: `magic_circle`, `sarcophagus`, `runestone`,
  `arcane_pillar`, `bookcase_tall`, `water_pool`, `sarcophagus_grand`,
  `spike_trap`, `ritual_brazier`, `obelisk`.

A library file is just a `.dmap` with no `map { }` block. New maps
created in the web app start with `include "core.dmap"` already in place.
