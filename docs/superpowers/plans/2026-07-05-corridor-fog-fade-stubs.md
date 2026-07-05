# Corridor Fog Fade Stubs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the fogged play view, soften abrupt corridor→corridor gaps by drawing ~1 grid cell of the unrevealed corridor's real geometry, faded to transparent.

**Architecture:** A pure play-layer function computes "fade stubs" from the full map + connectivity graph; `render_fogged` sets them on the renderer instance; the `classic_bw`/`hatched` renderer draws each stub as a normal two-stroke corridor piece wrapped in an SVG opacity-gradient mask. Other renderers ignore the stubs.

**Tech Stack:** Python 3, Pydantic models, pytest. Run tests with `uv run pytest` from the repo root.

## Global Constraints

- Stub length is **fixed at 1.0 map unit** (one grid cell) — no config knob.
- Fade rendering is implemented **only in `classic_bw`** (covers the `hatched`/`floorplan` aliases). Other renderers ignore `fade_stubs` — no regression, they keep today's hard edge.
- Trigger is narrow: revealed **corridor** → **open connector** (`edge.type == "open"`, not `edge.hidden`) → **unrevealed corridor**. Nothing else.
- Stubs only exist in the fogged view (`full=False`); the GM full view has none.
- No backend or web changes.
- Spec: `docs/superpowers/specs/2026-07-05-corridor-fog-fade-stubs-design.md`.

---

### Task 1: Play-layer detection + geometry

**Files:**
- Modify: `packages/dsl/src/dungml/play.py`
- Test: `packages/dsl/tests/test_fade_stubs.py` (create)

**Interfaces:**
- Consumes: `Graph.neighbors(node_id) -> list[(other_id, Edge)]`, `Edge.type`/`Edge.hidden`/`Edge.key`, `door_key(door)`, `build_graph(dmap)`, `Corridor.segments`/`Corridor.width`, `LineSegment.start`/`.end`.
- Produces:
  - `FadeStub` dataclass: `segments: list[Segment]`, `width: float`, `fade_from: Vec2`, `fade_to: Vec2`.
  - `clip_corridor(corr: Corridor, start: Vec2, length: float) -> list[LineSegment]`.
  - `corridor_fade_stubs(dmap: DungeonMap, graph: Graph, discovered_nodes: Iterable[str]) -> list[FadeStub]`.

- [ ] **Step 1: Write the failing test**

Create `packages/dsl/tests/test_fade_stubs.py`:

```python
"""Fog-of-war fade stubs: a revealed corridor continuing into an unrevealed
corridor through an open junction gets a short, fading piece of the hidden
corridor drawn beyond the boundary."""
from __future__ import annotations

from dungml import parse
from dungml.graph import build_graph, door_key
from dungml.play import clip_corridor, corridor_fade_stubs

TWO = """
map "T" {
  grid { cell 32 px units feet 5 bounds 10 x 10 origin top-left }
  renderer "hatched"
}
corridor "a" {
  width 1
  node n1 at 1,5
  node n2 at 5,5
  run n1 to n2
}
corridor "b" {
  width 1
  node n1 at 5,5
  node n2 at 9,5
  run n1 to n2
}
door at 5,5 {
  connects corridor.a, corridor.b
  type open
}
"""
CLOSED = TWO.replace("type open", "type wooden")


def test_clip_corridor_follows_length():
    dmap = parse(TWO)
    segs = clip_corridor(dmap.corridors["b"], (5.0, 5.0), 1.0)
    assert len(segs) == 1
    assert segs[0].start == (5.0, 5.0)
    assert abs(segs[0].end[0] - 6.0) < 1e-6
    assert abs(segs[0].end[1] - 5.0) < 1e-6


def test_detects_open_corridor_to_corridor_stub():
    dmap = parse(TWO)
    stubs = corridor_fade_stubs(dmap, build_graph(dmap), {"corridor.a"})
    assert len(stubs) == 1
    s = stubs[0]
    assert s.fade_from == (5.0, 5.0)
    assert abs(s.fade_to[0] - 6.0) < 1e-6
    assert abs(s.fade_to[1] - 5.0) < 1e-6
    assert s.width == 1.0


def test_no_stub_when_neighbor_discovered():
    dmap = parse(TWO)
    stubs = corridor_fade_stubs(
        dmap, build_graph(dmap), {"corridor.a", "corridor.b"}
    )
    assert stubs == []


def test_no_stub_through_closed_door():
    dmap = parse(CLOSED)
    stubs = corridor_fade_stubs(dmap, build_graph(dmap), {"corridor.a"})
    assert stubs == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/dsl/tests/test_fade_stubs.py -v`
Expected: FAIL — `ImportError: cannot import name 'clip_corridor'` (and `corridor_fade_stubs`).

- [ ] **Step 3: Write minimal implementation**

Edit `packages/dsl/src/dungml/play.py`. Extend the imports and add the new code.

Replace the import block at the top:

```python
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional

from .geometry import node_centroid
from .graph import Graph, build_graph, door_key, fog_of_war
from .model import (
    Corridor,
    DungeonMap,
    LineSegment,
    PartyStart,
    Segment,
    Vec2,
)
from .render import get_renderer
```

Add near the top of the module (after the imports, before `visible_doors`):

```python
_STUB_LEN = 1.0  # one grid cell; a corridor's width is already one cell
_EPS = 1e-9


@dataclass(frozen=True)
class FadeStub:
    """A ~1-cell piece of an *unrevealed* corridor, drawn beyond an open
    junction and faded to transparent so the fog boundary reads softly
    instead of stopping dead."""

    segments: list[Segment]  # clipped line segments of the hidden corridor
    width: float
    fade_from: Vec2  # the junction — opaque end of the gradient
    fade_to: Vec2  # far end of the stub — transparent end of the gradient


def _dist(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def clip_corridor(
    corr: Corridor, start: Vec2, length: float
) -> list[LineSegment]:
    """Line segments covering `length` units of `corr`, measured from the
    endpoint nearest `start` and walking along connected segments (so a bend
    within the clip is followed). Returns [] if `corr` has no line geometry."""
    segs = [s for s in corr.segments if isinstance(s, LineSegment)]
    if not segs:
        return []
    # Entry = the segment endpoint closest to `start`, oriented outward.
    best: Optional[tuple[float, int, Vec2, Vec2]] = None
    for i, s in enumerate(segs):
        for a, b in ((s.start, s.end), (s.end, s.start)):
            d = _dist(a, start)
            if best is None or d < best[0]:
                best = (d, i, a, b)
    assert best is not None
    _, cur_i, cur_from, cur_to = best
    remaining = length
    used: set[int] = set()
    out: list[LineSegment] = []
    while remaining > _EPS:
        seg_len = _dist(cur_from, cur_to)
        if seg_len <= _EPS:
            break
        if seg_len >= remaining:
            t = remaining / seg_len
            cut = (
                cur_from[0] + t * (cur_to[0] - cur_from[0]),
                cur_from[1] + t * (cur_to[1] - cur_from[1]),
            )
            out.append(LineSegment(start=cur_from, end=cut))
            break
        out.append(LineSegment(start=cur_from, end=cur_to))
        remaining -= seg_len
        used.add(cur_i)
        nxt: Optional[tuple[int, Vec2, Vec2]] = None
        for j, s in enumerate(segs):
            if j in used:
                continue
            for a, b in ((s.start, s.end), (s.end, s.start)):
                if _dist(a, cur_to) <= 1e-6:
                    nxt = (j, a, b)
                    break
            if nxt is not None:
                break
        if nxt is None:
            break
        cur_i, cur_from, cur_to = nxt
    return out


def corridor_fade_stubs(
    dmap: DungeonMap, graph: Graph, discovered_nodes: Iterable[str]
) -> list[FadeStub]:
    """Fade stubs for every open corridor→corridor junction that leaves the
    discovered subset. Computed from the *full* map (before fog pruning).
    Deterministic order (sorted) so mask ids are stable across renders."""
    discovered = set(discovered_nodes)
    pos_by_key: dict[str, Vec2] = {door_key(d): d.position for d in dmap.doors}
    corr_by_id: dict[str, Corridor] = {
        f"corridor.{name}": c for name, c in dmap.corridors.items()
    }
    for layer in dmap.layers:
        if layer.hidden:
            continue
        for d in layer.doors:
            pos_by_key.setdefault(door_key(d), d.position)
        for c in layer.corridors:
            corr_by_id.setdefault(f"corridor.{c.name}", c)

    stubs: list[FadeStub] = []
    for node_id in sorted(discovered):
        if not node_id.startswith("corridor."):
            continue
        for nbr, edge in sorted(
            graph.neighbors(node_id), key=lambda ne: (ne[0], ne[1].key)
        ):
            if nbr in discovered or not nbr.startswith("corridor."):
                continue
            if edge.hidden or edge.type != "open":
                continue
            junction = pos_by_key.get(edge.key)
            hidden = corr_by_id.get(nbr)
            if junction is None or hidden is None:
                continue
            segs = clip_corridor(hidden, junction, _STUB_LEN)
            if not segs:
                continue
            stubs.append(
                FadeStub(
                    segments=list(segs),
                    width=hidden.width,
                    fade_from=junction,
                    fade_to=segs[-1].end,
                )
            )
    return stubs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/dsl/tests/test_fade_stubs.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add packages/dsl/src/dungml/play.py packages/dsl/tests/test_fade_stubs.py
git commit -m "feat(dsl): compute corridor fog fade stubs (play layer)"
```

---

### Task 2: Renderer support (`classic_bw` draws faded stubs)

**Files:**
- Modify: `packages/dsl/src/dungml/render/__init__.py` (base `Renderer` default)
- Modify: `packages/dsl/src/dungml/render/classic_bw.py` (`ClassicBW.render`, `_RenderContext.__init__`, new `_fade_stubs_svg`, insert into `render()`)
- Test: `packages/dsl/tests/test_fade_stubs.py` (append)

**Interfaces:**
- Consumes: `FadeStub` (Task 1); `corridor_fade_stubs` (Task 1); `_RenderContext._corridor_path(Corridor) -> str`, `_corridor_floor_fill() -> str`, `self.y(v)`, `self.W`, `self.H`, module constant `WALL_STROKE = 0.18`, `_n(...)` number formatter.
- Produces: `Renderer.fade_stubs: list` (defaults to `[]`, set by callers before `render`); the rendered SVG gains a `<defs>` with `linearGradient`/`mask` ids `dungml-fade-grad-N`/`dungml-fade-N` and one `<g class="fade-stub" mask="url(#dungml-fade-N)">` per stub.

- [ ] **Step 1: Write the failing test**

Append to `packages/dsl/tests/test_fade_stubs.py`:

```python
from dungml.graph import fog_of_war
from dungml.render import get_renderer


def test_hatched_renders_stub_group_with_mask():
    dmap = parse(TWO)
    r = get_renderer("hatched")()
    r.fade_stubs = corridor_fade_stubs(dmap, build_graph(dmap), {"corridor.a"})
    svg = r.render(fog_of_war(dmap, {"corridor.a"}, set()))
    assert 'class="fade-stub"' in svg
    assert 'mask="url(#dungml-fade-0)"' in svg
    assert "linearGradient" in svg


def test_no_stubs_no_fade_markup():
    dmap = parse(TWO)
    r = get_renderer("hatched")()  # fade_stubs defaults to []
    svg = r.render(fog_of_war(dmap, {"corridor.a"}, set()))
    assert "dungml-fade" not in svg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/dsl/tests/test_fade_stubs.py -k "stub_group or no_stubs" -v`
Expected: FAIL — `AttributeError: 'Hatched' object has no attribute 'fade_stubs'`.

- [ ] **Step 3a: Add the base-class default**

In `packages/dsl/src/dungml/render/__init__.py`, give `Renderer` an `__init__` so every renderer instance has an (ignorable) `fade_stubs` list:

```python
class Renderer(ABC):
    """Abstract base for a map renderer.

    Subclasses set the class attribute `name` (used for registration
    and as the value of the `renderer` field in `.dmap`) and implement
    `render`.
    """

    name: ClassVar[str]

    def __init__(self) -> None:
        # Optional fog-of-war fade stubs, set by `render_fogged` before
        # `render`. Renderers that don't support fading ignore them.
        self.fade_stubs: list = []

    @abstractmethod
    def render(self, dmap: DungeonMap) -> str:
        """Render `dmap` and return the output as text (SVG)."""
```

- [ ] **Step 3b: Pass stubs into the render context and draw them**

In `packages/dsl/src/dungml/render/classic_bw.py`:

(1) `ClassicBW.render` — forward the stubs to the context:

```python
    def render(self, dmap: DungeonMap) -> str:
        ctx = self._context_for(dmap)
        ctx.fade_stubs = self.fade_stubs
        return ctx.render()
```

(2) `_RenderContext.__init__` — add a default at the very top of the body (right after `self.dmap = dmap`):

```python
        self.fade_stubs: list = []
```

(3) In `_RenderContext.render()`, immediately after the corridors group is appended (after the `parts.append("</g>")` that closes `<g class="corridors">`, around line 393), insert:

```python
        if self.fade_stubs:
            parts.append(self._fade_stubs_svg())
```

(4) Add the drawing method to `_RenderContext` (place it right after `_corridor_caps`):

```python
    def _fade_stubs_svg(self) -> str:
        """Fog-of-war fade stubs: each is a short corridor piece past an open
        junction, drawn like a normal two-stroke corridor but with no dead-end
        cap and wrapped in a linear-gradient opacity mask (opaque at the
        junction, transparent one cell out)."""
        defs: list[str] = []
        groups: list[str] = []
        floor = self._corridor_floor_fill()
        for i, stub in enumerate(self.fade_stubs):
            corr = Corridor(
                name=f"__fade{i}", width=stub.width, segments=list(stub.segments)
            )
            d = self._corridor_path(corr)
            if not d:
                continue
            gid = f"dungml-fade-grad-{i}"
            mid = f"dungml-fade-{i}"
            x1, y1 = stub.fade_from[0], self.y(stub.fade_from[1])
            x2, y2 = stub.fade_to[0], self.y(stub.fade_to[1])
            defs.append(
                f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" '
                f'x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}">'
                f'<stop offset="0" stop-color="#fff"/>'
                f'<stop offset="1" stop-color="#000"/></linearGradient>'
                f'<mask id="{mid}" maskUnits="userSpaceOnUse" x="0" y="0" '
                f'width="{_n(self.W)}" height="{_n(self.H)}">'
                f'<rect x="0" y="0" width="{_n(self.W)}" height="{_n(self.H)}" '
                f'fill="url(#{gid})"/></mask>'
            )
            outline_w = stub.width + 2 * WALL_STROKE
            wall = (
                f'<path class="corridor-wall" d="{d}" '
                f'stroke-width="{_n(outline_w)}" stroke="#111" '
                f'stroke-linejoin="round" stroke-linecap="butt" fill="none"/>'
            )
            floor_p = (
                f'<path class="corridor-floor" d="{d}" '
                f'stroke-width="{_n(stub.width)}" stroke="{floor}" '
                f'stroke-linejoin="round" stroke-linecap="butt" fill="none"/>'
            )
            groups.append(
                f'<g class="fade-stub" mask="url(#{mid})">{wall}{floor_p}</g>'
            )
        if not groups:
            return ""
        return f'<defs>{"".join(defs)}</defs>' + "".join(groups)
```

Note: `Corridor`, `LineSegment`, and `WALL_STROKE` are already imported/defined in `classic_bw.py`; no new imports needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/dsl/tests/test_fade_stubs.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Regression — full renderer suite**

Run: `uv run pytest packages/dsl/tests/ -q`
Expected: PASS (no existing test regresses; renders without stubs are byte-for-byte unchanged because `_fade_stubs_svg` is only reached when `self.fade_stubs` is truthy).

- [ ] **Step 6: Commit**

```bash
git add packages/dsl/src/dungml/render/__init__.py packages/dsl/src/dungml/render/classic_bw.py packages/dsl/tests/test_fade_stubs.py
git commit -m "feat(render): draw fog fade stubs with a gradient mask in classic_bw"
```

---

### Task 3: Wire `render_fogged` + end-to-end verification

**Files:**
- Modify: `packages/dsl/src/dungml/play.py` (`render_fogged`)
- Test: `packages/dsl/tests/test_fade_stubs.py` (append)

**Interfaces:**
- Consumes: `corridor_fade_stubs`, `build_graph` (Task 1); `Renderer.fade_stubs` (Task 2).
- Produces: `render_fogged(...)` output includes fade-stub markup when `full=False` and there is an open corridor→corridor gap; never when `full=True`.

- [ ] **Step 1: Write the failing test**

Append to `packages/dsl/tests/test_fade_stubs.py`:

```python
from dungml.play import render_fogged


def test_render_fogged_emits_fade_stub():
    dmap = parse(TWO)
    dk = door_key(dmap.doors[0])
    svg = render_fogged(dmap, {"corridor.a"}, {dk}, full=False)
    assert 'class="fade-stub"' in svg
    assert "dungml-fade-0" in svg


def test_render_fogged_full_has_no_fade_stub():
    dmap = parse(TWO)
    dk = door_key(dmap.doors[0])
    svg = render_fogged(dmap, {"corridor.a"}, {dk}, full=True)
    assert "dungml-fade" not in svg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/dsl/tests/test_fade_stubs.py -k render_fogged -v`
Expected: FAIL — `test_render_fogged_emits_fade_stub` fails (`'class="fade-stub"'` absent) because `render_fogged` doesn't compute/pass stubs yet.

- [ ] **Step 3: Write minimal implementation**

In `packages/dsl/src/dungml/play.py`, update `render_fogged` so the last lines become:

```python
    name = renderer or view.map.renderer
    r = get_renderer(name)()
    if not full:
        r.fade_stubs = corridor_fade_stubs(dmap, build_graph(dmap), discovered_nodes)
    return r.render(view)
```

(The `view` construction and the `party_location` marker block above are unchanged. `build_graph`/`corridor_fade_stubs` are already in this module from Task 1.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/dsl/tests/test_fade_stubs.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Full suite**

Run: `uv run pytest packages/dsl/tests/ -q`
Expected: PASS.

- [ ] **Step 6: Manual visual verification**

Render Level 1A fogged with a partial reveal and confirm the corridor→corridor gaps soften (opaque at the junction, transparent one cell out) with no artifacts:

```bash
uv run python - <<'PY'
from dungml import parse
from dungml.play import render_fogged
src = open("/tmp/level1a.dmap").read()  # export the map source first
dmap = parse(src)
# Reveal one corridor that opens onto an unrevealed corridor:
svg = render_fogged(dmap, {"corridor.corridor_15"}, set(), full=False)
open("/tmp/fogged.svg", "w").write(svg)
print("fade-stub" in svg, svg.count("class=\"fade-stub\""))
PY
```

Open `/tmp/fogged.svg` (or convert to PNG) and eyeball the junction. Expected: a short faded corridor nub past the revealed corridor's open end.

- [ ] **Step 7: Commit**

```bash
git add packages/dsl/src/dungml/play.py packages/dsl/tests/test_fade_stubs.py
git commit -m "feat(play): render fade stubs in the fogged view via render_fogged"
```

---

## Self-review notes

- **Spec coverage:** detection + open-connector trigger + junction lookup + 1.0-cell clip following bends (Task 1); gradient-mask drawing in `classic_bw` only + no far-end cap + no-regression path (Task 2); `render_fogged` wiring + `full=True` exclusion + visual check (Task 3). All spec sections map to a task.
- **Type consistency:** `FadeStub.{segments,width,fade_from,fade_to}` defined in Task 1 and consumed identically in Task 2's `_fade_stubs_svg`. Mask/gradient ids `dungml-fade-N` / `dungml-fade-grad-N` are consistent between the drawing code and the Task 2 assertions.
- **Determinism:** `corridor_fade_stubs` iterates `sorted(discovered)` and sorted neighbors, so stub indices (and therefore mask ids) are stable.
