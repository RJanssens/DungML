# Corridor fog-of-war fade stubs — design

## Problem

In the fogged play view (e.g. the map component ttrpg3 renders from the
campaign render URL), `fog_of_war` drops undiscovered corridors wholesale.
Where a revealed corridor continues into an *unrevealed* corridor through an
open (doorless) junction, the revealed corridor ends flush at the junction —
an abrupt, hard gap.

## Goal

Soften those gaps: draw a short piece (~1 grid cell) of the unrevealed
corridor beyond the junction, fading to transparent, so a corridor→corridor
continuation dissolves into the fog instead of stopping dead.

## Scope

- **In scope:** a *revealed corridor* continuing into an *unrevealed corridor*
  through an **open connector** (`type open`, non-secret door).
- **Out of scope:** corridor→room and room→corridor boundaries; closed/secret
  doors (they draw a door leaf and are not perceived as a gap); the GM full
  view (nothing is hidden there).
- **No client changes:** ttrpg3 keeps polling the same render URL; it just gets
  softer edges.

## Design

Approach A (chosen): the play layer computes stub geometry from graph +
geometry reasoning; the `classic_bw` / `hatched` renderer draws each stub with
an SVG opacity gradient. Other renderers ignore stubs (no regression). This
matches the existing split where fog logic lives in the play layer and the
renderer stays mostly dumb.

### Part 1 — Detection + geometry (`packages/dsl/src/dungml/play.py`)

New pure function, computed from the **full** map (before pruning):

```python
def corridor_fade_stubs(
    dmap: DungeonMap, graph: Graph, discovered_nodes: Iterable[str],
) -> list[FadeStub]: ...
```

**Detection** — for each discovered `corridor.*` node, walk
`graph.neighbors(node)`; emit a stub when the neighbor is:
- a corridor (`neighbor` id starts with `corridor.`), **and**
- not in `discovered_nodes`, **and**
- reached by an **open connector**: `edge.type == "open"` and not `edge.hidden`.

**Junction point** — the connecting door's `at` position, looked up from the
map by `edge.key` (the door key the edge is backed by).

**Clip geometry** — `clip_corridor(hidden, from=junction, length=1.0)`:
- find the hidden corridor's segment endpoint nearest the junction,
- walk outward along its segments accumulating **1.0 map unit** (one grid
  cell; corridor width is already one cell), following any bend within the
  cell (this is the "true hidden geometry" the stub traces),
- if the hidden corridor is shorter than 1.0 unit, take all of it.

**Output** — one `FadeStub` per gap:

```python
@dataclass(frozen=True)
class FadeStub:
    segments: list[Segment]   # clipped ~1-cell piece of the hidden corridor
    width: float              # hidden corridor's width
    fade_from: Vec2           # junction point — opaque end
    fade_to: Vec2             # far end of the stub — transparent end
```

The renderer turns `segments` + `width` into a polygon with the existing
`corridor_polygons`, and uses `fade_from → fade_to` as the gradient axis.

### Part 2 — Rendering (`packages/dsl/src/dungml/render/classic_bw.py`)

**Plumbing (no ABC or model change).** `render_fogged` computes stubs only for
the fogged view (`full=False`) and sets them on the renderer instance before
drawing:

```python
r = get_renderer(name)()
r.fade_stubs = stubs   # base Renderer defaults this to []; other renderers ignore it
return r.render(view)
```

`render(dmap)` signature is untouched; the core model stays clean; only
`classic_bw` reads `self.fade_stubs`.

**Drawing.** After the normal `<g class="corridors">`, for each stub emit a
`<g mask="url(#fade-N)">` containing the stub drawn like a normal corridor
floor + walls (reusing `corridor_polygons` and the existing corridor
fill/wall styling), with two differences:
- the **far end is not capped** — no wall line in the fog, it just fades;
- the group is wrapped in an opacity mask.

Each mask is a `<linearGradient>` in `<defs>`, `userSpaceOnUse`, running
`fade_from → fade_to`: white (opaque) at the junction → black (transparent)
at the far end. Anchored at the true junction, the stub reads as a seamless
continuation of the revealed corridor and dissolves one cell out.

## Edge cases

- GM full view (`full=True`): no stubs.
- Multiple unrevealed-corridor neighbors from one corridor: multiple stubs.
- Bend within the cell: stub follows the real path.
- Closed/secret doors: skipped.
- Hidden corridor shorter than one cell: stub is the whole hidden corridor.

## Testing

- **`dsl` unit — `corridor_fade_stubs`:** two-corridor map, one discovered →
  one stub with expected `fade_from`, direction, and ~1.0 length; closed-door
  variant → no stub; full view → no stub.
- **`classic_bw` render:** with a stub present, the SVG contains the
  `linearGradient`/`mask` and the stub group; with none, neither appears
  (regression guard).
- **Visual:** re-render Level 1A fogged with a partial reveal and confirm the
  corridor→corridor gaps soften.

## Files touched

- `packages/dsl/src/dungml/play.py` — `FadeStub`, `corridor_fade_stubs`,
  `clip_corridor`; wire stubs through `render_fogged`.
- `packages/dsl/src/dungml/render/__init__.py` — `fade_stubs = []` default on
  the base `Renderer`.
- `packages/dsl/src/dungml/render/classic_bw.py` — draw faded stubs + gradient
  masks.
- Tests under `packages/dsl/tests/`.

No backend or web changes.
