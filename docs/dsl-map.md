# Map header

Part of the [dungml DSL reference](/docs/dsl).

## `map` — required header

Every file must contain exactly one `map`:

```dmap
map "The Sunken Library" {
  grid {
    cell   20 px
    units  feet 5
    bounds 100 x 70
    origin top-left
  }
  renderer "classic-bw"
  theme    dark
  party_start 4,4          # optional: where the PCs begin on load
}
```

### `party_start`

`party_start X,Y` (optional) marks the party's starting cell — where the
characters begin when the map loads. It's drawn as a green **S** marker and
can be used by play-sessions as the default party location.

### `room_numbers`

Rooms are auto-numbered in source order, and on-map labels are prefixed with
that number (`1. Hall`). `room_numbers off` in the map block suppresses the
prefix so labels render bare (`Hall`). Default `on`.

### `grid`

| Property | Form | Default | Meaning |
|----------|------|---------|---------|
| `cell N px`        | integer pixels | `32`  | Pixel size of one world-unit cell in the output SVG |
| `units NAME N`     | `units feet 5` | none  | Real-world unit name and how many of them per cell |
| `bounds W x H`     | two numbers    | `60 x 40` | Map extent in world units |
| `origin K`         | `top-left` \| `bottom-left` | `top-left` | Which corner is `(0,0)` |

### `renderer`

Pick the visual style. Built-in renderers:

- `"classic-bw"` — flat fill, hard outline. Dungeon default.
- `"floorplan"` — alias of `classic-bw`. Use for buildings.
- `"hatched"` — diagonal hatching outside walls. Architectural drawing style.
- `"oldschool-blue"` — classic blue-ink dungeon style: blue line-work over a
  solid blue page with white room floors, so rooms read as carved out of rock.
  A `grid_overlay` / `cell_grid` is tinted blue to match if the map declares
  one (no grid is forced).

If omitted, defaults to `"classic-bw"`.

### `theme`

A renderer-specific hint, e.g. `theme dark`. The built-in renderers
accept it but do not currently change palette; the field is preserved
in the parsed model for downstream consumers.

### `grid_overlay` — graph-paper grid across the canvas

A faint grid drawn across the whole map. Useful for tactical / square-
based grids on outdoor or freeform maps where you don't have a single
"room" to attach a per-room grid to.

```dmap
map "X" {
  grid { cell 20 px bounds 60 x 40 }
  grid_overlay                  # default — 1-unit spacing, default colour
  # grid_overlay 2              # 2-unit spacing
  # grid_overlay 1 "#444444"    # 1-unit spacing, custom colour
}
```

| Form                       | Result |
|----------------------------|--------|
| (omitted)                  | No overlay (default). |
| `grid_overlay`             | 1 world-unit spacing, default faint grey. |
| `grid_overlay N`           | N-unit spacing. |
| `grid_overlay N "#color"`  | N-unit spacing with explicit CSS colour. |

The overlay is drawn AFTER all map content (rooms, corridors, slices,
features) but BEFORE labels, so labels remain readable on top of it.
Per-room `grid` overlays still work and are clipped to their room — the
two stack cleanly when both are set.
