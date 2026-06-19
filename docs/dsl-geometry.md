# Geometry

Part of the [dungml DSL reference](/docs/dsl). Covers the spatial
declarations: rooms, corridors, slices, doors, windows, markers, layers.

## `room` — walled spaces

```dmap
room "kitchen" {
  rect 2,2 8 x 7
  label "Kitchen"
  description "Flour on every surface."
  dm_notes  "Hidden trapdoor under the rug at (5,5)."

  feature hearth at 9,4 rotate 90
  feature table  at 6,6 {
    description "Flour-dusted oak slab."
  }
}
```

| Property      | Notes |
|---------------|-------|
| shape decl    | exactly one of `rect`, `circle`, `polygon`, `boundary { ... }` |
| `label`       | optional, see below |
| `description` | text shown to players ("read aloud") |
| `dm_notes`    | private text — traps, secrets, hooks |
| `feature`     | zero or more — see [feature instance](/docs/dsl-features) |
| `grid N`      | overlay a per-room sub-grid at spacing `N` (world units) |
| `line_style K [N]` | wall edge style: `solid` (default) or `organic` (hand-drawn wobble). For `organic`, an optional number scales the waviness (`1.0` default, e.g. `line_style organic 3` = wavier, `0.5` = subtler). Also valid on `corridor`. |

Features placed in a room are listed with `feature` lines; the syntax
and built-in names are documented in
**[Features & glyphs](/docs/dsl-features)**.

### Shapes

```dmap
rect 2,2 8 x 7
circle at 15,15 radius 8
polygon (0,0) (10,0) (12,4) (10,8) (0,8)
boundary {
  start 4,22
  line to 17,22
  arc  to 17,40 via 23,31
  line to 4,40
  line to 4,22
}
```

- `rect X,Y W x H` — axis-aligned, `X,Y` is the top-left corner.
- `circle at X,Y radius R` — `X,Y` is the centre. Treated geometrically as
  a finely-sampled polygon, so walls, door cut-outs, and overlap checks all
  work the same as for any other room.
- `polygon (x,y) ...` — three points minimum, implicitly closed.
- `boundary { ... }` — mixed straight + arc edges. `start` is required.
  Each `line to X,Y` adds a straight edge ending at the point. Each
  `arc to X,Y via X,Y` adds a circular arc ending at `to`, passing
  through `via` — three points uniquely determine the arc. The
  boundary is implicitly closed by the renderer.

### `label`

```dmap
label "Grand Library" at 46,9 size 1.4 rotate 0
label "Atrium"        align top center
label "Vault"         align bottom right size 0.9
```

| Modifier        | Default | Notes |
|-----------------|---------|-------|
| `at X,Y`        | room centroid | Absolute world coords. |
| `align V H`     | none → centroid | Relative to the room's bounding box. `V` is `top` \| `middle` \| `bottom`; `H` is `left` \| `center` \| `right`. Vertical first. |
| `size N`        | `1.0` | Multiplier; renderer picks a base size. |
| `rotate N`      | `0` (degrees) | |

`at` and `align` are mutually exclusive in effect — if both are
specified, `at` wins. Aligned labels also align the text itself
(`left` → text-anchor start, `right` → end, `top` → baseline at the
top of the glyph, etc.) so the text doesn't overflow the room.

---

## `corridor` — connecting passages

```dmap
corridor "atrium_to_library" {
  width 2
  segment line from 20,11 to 26,11
}

corridor "back_crawl" "Back Crawl" {       # second STRING is a display name —
  width 1                                  # shown in tooltips / print legend,
  segment line from 5,4 to 25,4            # never drawn on the map.
}

corridor "named_route" "Pilgrim's Way" {   # opt-in on-map label: include an
  width 1.5                                # explicit `label` block.
  segment line from 10,5 to 40,5
  label "Pilgrim's Way" align top center size 0.8
}
```

| Property        | Notes |
|-----------------|-------|
| `width N`       | world units, default `1.0` |
| `segment`       | zero or more (see below) |
| `node NAME at X,Y` | a named junction point (see "Branches and intersections") |
| `run A to B`    | a straight run between two named nodes |
| `label "..."`   | optional on-map label. Same modifiers as room labels (`at X,Y`, `align V H`, `size N`, `rotate N`). With no `at`/`align`, the label is auto-placed along the longest line segment and rotated to read along the corridor. |
| `description`   | optional |
| `dm_notes`      | optional |

The second `STRING` immediately after the slug (e.g. `"Back Crawl"` above)
is a **display name** used only by the tooltip and the print key. It is
*never* rendered as text on the map. To draw a corridor label on the map,
add an explicit `label "..."` block inside the corridor.

### Segment kinds

```dmap
segment line from X,Y to X,Y
segment arc  center X,Y radius N from-angle DEG to-angle DEG sweep ccw
```

- `line` is a straight segment between two points.
- `arc` describes a circular arc by center, radius, and start/end
  angles in degrees. `sweep` is optional and is one of `ccw` (default)
  or `cw`.

### Branches and intersections

A single corridor can branch. Instead of chasing coordinates, name the
junction points with `node` and join them with `run`:

```dmap
corridor "crossroads" {
  width 2
  node hub at 15,15
  node n   at 15,4
  node s   at 15,26
  node e   at 26,15
  node w   at 4,15
  run hub to n      # ┐
  run hub to s      # ┤ four runs sharing `hub` → a 4-way crossing
  run hub to e      # ┤ (3 runs → a T-junction; ≥3 from any node → a branch)
  run hub to w      # ┘
}
```

- A `run A to B` is a **straight** segment between two named nodes. The
  number of runs meeting at a node sets the junction: two collinear runs
  read as a straight pass-through, three as a **T**, four as a **crossing**,
  and any node with three-or-more runs is a **branch**. Runs that form a
  cycle make a **loop**.
- Nodes guarantee that the meeting runs share *exactly* one point, so the
  renderer draws a clean junction (no parallel-wall stitching, no sliver
  overlap warnings against the corridor itself).
- Curved branches: keep using `segment arc` for the curved leg — `run` and
  `segment` can be mixed freely in the same corridor.
- A branching corridor is still **one node in the connectivity graph**
  (see [Validation & tooling](/docs/dsl-tooling)): the whole shape is one
  connected space, so it is fully traversable without placing a door at
  every junction. This is the recommended way to author an intersecting
  passage network — model it as a single corridor rather than many
  corridors that merely touch.

`run`s are sugar: they desugar into `line` segments, so everything that
consumes segments (rendering, overlap checks, the graph) works unchanged.

---

## `slice` — cross-slice terrain (rivers, ravines, splits)

A `slice` cuts ACROSS the map rather than connecting rooms. The geometry
is the same as a corridor (line + arc segments with a width), but the
rendering treats the band as terrain — water for rivers, dirt with shadow
for ravines, a hairline crack for splits.

```dmap
slice "river_branwen" {
  kind  river                  # river | ravine | split
  width 3.2
  segment line from 22,0  to 22,8
  segment arc  center 24,11 radius 3 from-angle 180 to-angle 270 sweep ccw
  segment line from 23,17 to 23,28
  label "R. Branwen" at 26,23 rotate -85 size 0.9
  description "Cold and quick. Knee-deep at the ford."
}

# A bridge is the built-in `bridge` feature placed on top of the slice.
# Default deck is 1.6 (along) × 1.0 (across); rotate to align with the
# slice direction and scale to match its width.
feature bridge at 22,14 rotate 90 scale 1.4 {
  description "Three squat stone arches."
}
```

| Property        | Notes |
|-----------------|-------|
| `kind K`        | `river` (blue band + flow dashes), `ravine` (dirt band + depth shadow), `split` (thin dark crack). Default `river`. |
| `width N`       | World units. For `split` this acts as the soft-shadow width since the crack itself is always thin. Default `2.0`. |
| `segment`       | Same `line` / `arc` syntax as corridors. |
| `label "..."`   | Optional, same modifiers as room labels. With no `at`/`align`, the label auto-orients along the longest line segment. |
| `description`   | Optional. |
| `dm_notes`      | Optional. |

Slices render after corridors and before doors/windows/features, so
bridges and other crossing features sit cleanly on top of the band.
The slice itself does **not** model crossings or movement obstruction —
that's purely a feature-placement convention.

The `bridge` built-in (deck rectangle with rails and plank ticks) comes
from `core.dmap`, so `include "core.dmap"` to use it. It can also be
placed independently of any slice — e.g. a deck over a corridor — and as
a top-level declaration outside any room.

---

## `door` — openings on walls

```dmap
door at 15,2 {
  connects room.parlor
  type     wooden
  state    closed
  facing   south
  width    2
  description "Heavy oak. The hinges complain."
}
```

| Property      | Default       | Notes |
|---------------|---------------|-------|
| `connects`    | required for full semantics | One or two `room.NAME` / `corridor.NAME` refs, comma-separated |
| `type`        | `wooden`      | `wooden`, `iron`, `stone`, `secret` (`S`-in-circle on wall), `concealed` (`C`-in-circle on wall), `smashed` (arch with debris), `arch`, `portcullis`, `open` (bare gap), `double` (two leaves), `one-way` |
| `state`       | `closed`      | `open`, `closed`, `locked` (`arch` / `open` ignore state) |
| `facing`      | inferred      | `north`, `south`, `east`, `west` — hints the leaf side; sets the `one-way` arrow direction |
| `width`       | `1.0`         | World units across the opening |
| `description` | none          | Long-form text |

A door's position should sit *on a wall*; renderers project it onto
the nearest wall within ~½ world unit. Doors that miss every wall by
more than that are drawn as a small circle at the literal position.

`type open` draws nothing (the wall gap is the door) but is still a real
connector. `type one-way` is passable in one direction only — from the
first `connects` reference to the second — and the connectivity graph /
pathfinding honour that.

`type secret` draws as an S-in-circle on top of the wall with no
opening cut.

`connects` may name only one side (e.g. a front door whose other side
is exterior). At least one `connects` is recommended — validation
emits a warning when missing.

---

## `window` — slits on exterior walls

```dmap
window at 4,9 { in room.entry_atrium width 1.5 }
```

| Property      | Notes |
|---------------|-------|
| `in`          | required — `room.NAME` or `corridor.NAME` |
| `width`       | default `1.0` |
| `description` | optional |

Like doors, the position is projected onto the nearest wall of the
named room.

---

## `marker` — dynamic tokens (party, NPCs, monsters)

```dmap
marker "Aragorn" at 5,5 tag party initial "A"
marker "Goblin Boss" at 20,4
    tag boss
    label "Broken-Tooth"
    size 0.6
    image "tokens/goblin-boss.png"
    in room.guardroom
    description "Wields a notched scimitar."
    dm_notes "Surrenders below 6 HP."
```

A marker is a lightweight named token placed at a single point on the
map. Unlike `feature`, which is static furniture, markers represent
*who is here right now* — party members, NPCs, monsters — so they're
typically rewritten between scenes by an outer tool (e.g. a combat
tracker) rather than authored once.

| Property      | Notes |
|---------------|-------|
| `at X,Y`      | required — token position in world units |
| `tag`         | palette key (`party`, `ally`, `npc`, `enemy`, `boss`, `neutral`, `unknown`) **or** a CSS color literal in quotes (`tag "#ff8800"`). Default `neutral`. |
| `label`       | optional display caption rendered below the token. Defaults to no caption. |
| `initial`     | 1–2 character glyph drawn inside the disc. Default: first character of the name. Ignored when `image` is set. |
| `size`        | token radius in world units. Default `0.5`. |
| `in`          | optional `room.NAME` / `corridor.NAME` reference, recorded as a `data-location` attribute on the rendered group. |
| `image`       | optional path or URL to a portrait. When set, the renderer emits an `<image>` clipped to the token circle and uses `tag` as the ring color instead of the disc fill. |
| `description` | optional free text — surfaced via `data-description`. |
| `dm_notes`    | optional DM-only text — surfaced via `data-dm-notes`. |

The colored disc/ring uses the tag palette so party / ally / enemy /
boss read at a glance even when the portrait art doesn't follow a
strict convention.

Markers inside a `hidden` layer are parsed and validated, but the
renderer skips them — useful for tokens that should only appear in
DM-facing exports.

---

## `layer` — grouping declarations

```dmap
layer "secrets" hidden {
  feature trap at 84,32 {
    description "Floor plate. Releases steam from the niche above."
  }
  feature chest at 88,38
}
```

A layer wraps any number of `room`, `corridor`, `feature`, `door`, and
`window` declarations. The `hidden` flag tells renderers to omit the
layer from the visible output — useful for DM-only secrets that
still parse and validate alongside the rest of the map.

Rooms inside a hidden layer do not contribute to room numbering or
visible walls. Doors and windows inside a hidden layer are skipped
likewise.
