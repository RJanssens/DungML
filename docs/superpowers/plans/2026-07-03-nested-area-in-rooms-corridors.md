# Nested `area` in Rooms & Corridors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `area` blocks to be authored inside `room { … }` and `corridor { … }` blocks, so a decorative area (pool/lava/pit) is bound to its parent node — absolute coords, not hoisted, and pruned by fog-of-war together with the parent.

**Architecture:** A pure Python DSL change (dungml). `Area` already exists as a top-level primitive; this threads it through the nested room/corridor grammar → parser → model → renderer, mirroring how `line_features`/`texts` are already nested. Fog needs no change (nested items ride with their room in `fog_of_war`). One `_all_areas()` edit covers both renderers (`OldSchoolBlue` extends `ClassicBW`).

**Tech Stack:** Python 3.12, Lark grammar, Pydantic v2 model, pytest, `uv` workspace.

## Global Constraints

- Tests run with `uv run pytest` from the dungml repo root (`/home/raf/roleplaying/dungml`).
- A nested `area` uses absolute world coords, is NOT hoisted to the map level, and is pruned by fog with its parent room/corridor — identical semantics to `Room.texts` / `Room.line_features`.
- Decorative `area` objects (top-level OR nested) never participate in the interior-overlap validation warning: that warning's geometry set is built only from room/corridor polygons, so nested areas are excluded automatically — **no code needed**, verify by test.
- NO web, Monaco (`dmapLanguage.ts`), or draw-tool (`draw.ts`) changes: the preview is server-rendered and `area` is already a highlighted keyword.
- NO per-area `secret` flag.
- `from __future__ import annotations` is already at the top of `model.py`; `list[Area]` on `Room`/`Corridor` is a forward reference resolved the same way the existing `list[Exit]` / `list[LineFeature]` fields are.
- Stage only the files each task's commit step lists — never `git add -A`.

---

### Task 1: Parse a nested `area` onto `Room.areas` / `Corridor.areas`

**Files:**
- Modify: `packages/dsl/src/dungml/model.py` (`Room` ~line 245, `Corridor` ~line 318)
- Modify: `packages/dsl/src/dungml/grammar.lark` (`room_property` ~line 174, `corridor_property` ~line 261)
- Modify: `packages/dsl/src/dungml/parser.py` (`room` ~line 774, `corridor` ~line 876)
- Test: `packages/dsl/tests/test_area_nested.py` (new)

**Interfaces:**
- Consumes: existing `Area` model (already imported in `parser.py` at line 58).
- Produces: `Room.areas: list[Area]` and `Corridor.areas: list[Area]`, populated by the parser from nested `area "…" { … }` blocks.

- [ ] **Step 1: Write the failing tests**

Create `packages/dsl/tests/test_area_nested.py`:

```python
"""`area` blocks authored inside room / corridor blocks.

The nesting binds the area to its node (absolute coords): it stays on the
room/corridor and is NOT hoisted to the map level, so — like a nested text —
it renders only when that node is visible (fog prunes the node and its area
together).
"""
from __future__ import annotations

from dungml import Area, parse


def test_area_nested_in_room_stays_on_room_not_hoisted() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    room "hall" {
      rect 2,2 10 x 8
      area "pool" kind water { rect 4,4 3 x 3 }
    }
    """
    m = parse(src)
    # Kept on the room...
    assert len(m.rooms["hall"].areas) == 1
    a = m.rooms["hall"].areas[0]
    assert isinstance(a, Area)
    assert a.name == "pool"
    assert a.kind == "water"
    # ...and NOT hoisted to the map level.
    assert len(m.areas) == 0


def test_area_nested_in_corridor() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    corridor "c" {
      width 2
      segment line from 12,6 to 24,6
      area "spill" kind lava { rect 16,5 3 x 2 }
    }
    """
    c = parse(src).corridors["c"]
    assert len(c.areas) == 1
    assert c.areas[0].name == "spill"
    assert c.areas[0].kind == "lava"


def test_top_level_area_still_lands_on_map() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    area "lake" kind water { rect 1,1 4 x 4 }
    room "hall" { rect 10,2 8 x 8 }
    """
    m = parse(src)
    assert len(m.areas) == 1
    assert len(m.rooms["hall"].areas) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/dsl/tests/test_area_nested.py -v`
Expected: the two nested tests FAIL — the grammar rejects `area` inside a room/corridor block (a Lark parse error), or `Room` has no `areas` attribute. (`test_top_level_area_still_lands_on_map` passes already.)

- [ ] **Step 3: Add the model fields**

In `packages/dsl/src/dungml/model.py`, in `class Room`, immediately after the `line_features` field (the block ending ~line 245), add:

```python
    # Decorative areas (pools, pits, lava, …) authored inside this room's block
    # (absolute world coords). NOT hoisted — render only when the room is
    # visible, like texts/line_features; fog prunes them with the room.
    areas: list[Area] = Field(default_factory=list)
```

In `class Corridor`, immediately after its `line_features` field (~line 318), add:

```python
    # Decorative areas authored inside this corridor's block (absolute coords).
    # NOT hoisted — render only when the corridor is visible. See Room.areas.
    areas: list[Area] = Field(default_factory=list)
```

- [ ] **Step 4: Add `area` to the nested grammar rules**

In `packages/dsl/src/dungml/grammar.lark`, add `| area` to `room_property` (after the `line_feature` alternative, ~line 175) and to `corridor_property` (after its `line_feature` alternative, ~line 262). After the edit `room_property` reads:

```
?room_property: room_shape
              | label_decl
              | description_decl
              | dm_notes_decl
              | feature_inst
              | exit_decl
              | text_annotation
              | line_feature
              | area
              | room_grid
              | background_prop
              | line_style_decl
              | allow_overlap_decl
```

and `corridor_property` gains a `| area` line after its `| line_feature`.

- [ ] **Step 5: Collect nested areas in the parser**

In `packages/dsl/src/dungml/parser.py`, in `def room` (~line 774): add a local list and an isinstance branch, then pass it to `Room(...)`.

After `line_features: list[LineFeature] = []` (line 783) add:
```python
        areas: list[Area] = []
```
In the item loop, after the `LineFeature` branch (lines 799-800) add:
```python
            elif isinstance(item, Area):
                areas.append(item)
```
In the `Room(...)` constructor call, after `line_features=line_features,` (line 828) add:
```python
            areas=areas,
```

In `def corridor` (~line 876): after `line_features: list[LineFeature] = []` (line 901) add:
```python
        areas: list[Area] = []
```
In the item loop, after the `LineFeature` branch (lines 911-912) add:
```python
            elif isinstance(item, Area):
                areas.append(item)
```
In the `Corridor(...)` constructor call, after `line_features=line_features,` (line 952) add:
```python
            areas=areas,
```

(The `Area` isinstance branch must sit among the model-instance branches, before the `elif isinstance(item, tuple)` branch, because `Area` is a Pydantic model, not a tuple.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest packages/dsl/tests/test_area_nested.py -v`
Expected: all three tests PASS.

- [ ] **Step 7: Run the DSL suite to catch regressions (grammar/model are shared)**

Run: `uv run pytest packages/dsl/tests/ -q`
Expected: PASS (no regressions in existing area/parser/render tests).

- [ ] **Step 8: Commit**

```bash
git add packages/dsl/src/dungml/model.py \
        packages/dsl/src/dungml/grammar.lark \
        packages/dsl/src/dungml/parser.py \
        packages/dsl/tests/test_area_nested.py
git commit -m "feat(dsl): parse nested area blocks in rooms & corridors

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Render nested areas (and confirm fog prunes them)

**Files:**
- Modify: `packages/dsl/src/dungml/render/classic_bw.py` (`_all_areas` ~line 613)
- Test: `packages/dsl/tests/test_area_nested.py` (append)

**Interfaces:**
- Consumes: `Room.areas` / `Corridor.areas` from Task 1; `dungml.render`, `dungml.render_fogged`.
- Produces: nested areas emitted in the rendered SVG (as `class="area"` elements), pruned in the fogged view when the parent is undiscovered.

- [ ] **Step 1: Write the failing tests**

Append to `packages/dsl/tests/test_area_nested.py`:

```python
import xml.etree.ElementTree as ET

from dungml import render, render_fogged

SVG_NS = "{http://www.w3.org/2000/svg}"


def _area_count(svg: str) -> int:
    root = ET.fromstring(svg)
    return sum(1 for e in root.iter() if e.get("class") == "area")


def test_nested_area_renders() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    room "hall" {
      rect 2,2 10 x 8
      area "pool" kind water { rect 4,4 3 x 3 }
    }
    """
    assert _area_count(render(parse(src))) == 1


def test_nested_area_hidden_when_room_undiscovered() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    room "a" { rect 2,2 8 x 8 }
    room "b" { rect 18,2 8 x 8
      area "pit" kind pit { rect 20,4 3 x 3 }
    }
    door at 10,5 { connects room.a, room.b }
    """
    m = parse(src)
    # room.b not discovered → its nested area is absent from the players' view.
    hidden = render_fogged(m, {"room.a"}, set(), party_location="room.a")
    assert _area_count(hidden) == 0
    # room.b discovered → its nested area shows.
    shown = render_fogged(m, {"room.a", "room.b"}, {"10,5"}, party_location="room.a")
    assert _area_count(shown) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/dsl/tests/test_area_nested.py -k "renders or hidden" -v`
Expected: `test_nested_area_renders` FAILS with `0 == 1` (nested areas aren't collected for drawing yet); `test_nested_area_hidden_when_room_undiscovered` FAILS on the discovered assertion (`0 == 1`).

- [ ] **Step 3: Extend `_all_areas()`**

In `packages/dsl/src/dungml/render/classic_bw.py`, replace `_all_areas` (lines 613-620) with:

```python
    def _all_areas(self) -> list[Area]:
        """Top-level areas, those in visible layers, and areas nested inside
        rooms/corridors (which ride with their parent through fog)."""
        areas: list[Area] = list(self.dmap.areas)
        for layer in self.dmap.layers:
            if layer.hidden:
                continue
            areas.extend(layer.areas)
        for r in self.dmap.rooms.values():
            areas.extend(r.areas)
        for c in self.dmap.corridors.values():
            areas.extend(c.areas)
        return areas
```

(Nested areas ride the same z-order as top-level areas — above room floors, below walls/features. `OldSchoolBlue` extends `ClassicBW`, so this covers both renderers. In the fogged view, `render_fogged` has already pruned `self.dmap.rooms`/`corridors` to the discovered set, so an undiscovered room's areas are gone before `_all_areas()` runs.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/dsl/tests/test_area_nested.py -v`
Expected: all tests PASS (5 total).

- [ ] **Step 5: Run the render + fog suites for regressions**

Run: `uv run pytest packages/dsl/tests/test_render_classic.py packages/dsl/tests/test_area.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/dsl/src/dungml/render/classic_bw.py \
        packages/dsl/tests/test_area_nested.py
git commit -m "feat(dsl): render room/corridor-nested areas (fog prunes with parent)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Validate nested areas (per-area checks; no spurious overlap warning)

**Files:**
- Modify: `packages/dsl/src/dungml/validate.py` (after the top-level area loop ~line 365; the layer loop ~line 446)
- Test: `packages/dsl/tests/test_area_nested.py` (append)

**Interfaces:**
- Consumes: `Room.areas` / `Corridor.areas`; the existing `check_area(a, *, scope)` helper (validate.py ~line 343); `dungml.validate.validate`.
- Produces: nested areas run through the same degenerate-polygon / unknown-kind checks top-level areas get, scoped to their parent. Nested areas raise no interior-overlap warning (already guaranteed — verified).

- [ ] **Step 1: Write the failing tests**

Append to `packages/dsl/tests/test_area_nested.py`:

```python
from dungml.validate import validate


def test_nested_area_unknown_kind_warns() -> None:
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    room "hall" {
      rect 2,2 10 x 8
      area "weird" kind glowmoss { rect 4,4 2 x 2 }
    }
    """
    diags = validate(parse(src))
    msgs = [d.message for d in diags]
    assert any("weird" in m and "unknown kind" in m and "room 'hall'" in m for m in msgs)


def test_nested_area_raises_no_overlap_warning() -> None:
    # A pool nested inside its room legitimately overlaps the room; it must not
    # trip the interior-overlap warning (decorative areas are never in the
    # overlap geometry set).
    src = """
    map "M" { grid { bounds 30 x 16 } renderer "classic-bw" }
    room "hall" {
      rect 2,2 10 x 8
      area "pool" kind water { rect 4,4 3 x 3 }
    }
    """
    diags = validate(parse(src))
    assert not any("overlap" in d.message.lower() for d in diags)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/dsl/tests/test_area_nested.py -k "unknown_kind or overlap" -v`
Expected: `test_nested_area_unknown_kind_warns` FAILS (nested areas aren't validated yet, so no diagnostic is emitted). `test_nested_area_raises_no_overlap_warning` PASSES already (confirming decorative areas are outside the overlap set — keep it as a guard).

- [ ] **Step 3: Validate nested areas**

In `packages/dsl/src/dungml/validate.py`, immediately after the top-level area loop (lines 365-366):

```python
    for a in dmap.areas:
        check_area(a, scope="map")
```

add:

```python
    for name, room in dmap.rooms.items():
        for a in room.areas:
            check_area(a, scope=f"room '{name}'")
    for name, corr in dmap.corridors.items():
        for a in corr.areas:
            check_area(a, scope=f"corridor '{name}'")
```

Then, inside the `for layer in dmap.layers:` block: the `for room in layer.rooms:` loop (~line 456) and the `for corr in layer.corridors:` loop (~line 463) already exist, each ending with a `check_line_feature` call. In the `for room in layer.rooms:` loop, after its `check_line_feature(...)` call (~line 462) add:

```python
            for a in room.areas:
                check_area(a, scope=f"layer '{layer.name}' room '{room.name}'")
```

In the `for corr in layer.corridors:` loop, after its `check_line_feature(...)` call (~line 469) add:

```python
            for a in corr.areas:
                check_area(
                    a, scope=f"layer '{layer.name}' corridor '{corr.name}'"
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/dsl/tests/test_area_nested.py -v`
Expected: all tests PASS (7 total).

- [ ] **Step 5: Run the validation suite for regressions**

Run: `uv run pytest packages/dsl/tests/test_overlap.py packages/dsl/tests/test_area.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/dsl/src/dungml/validate.py \
        packages/dsl/tests/test_area_nested.py
git commit -m "feat(dsl): validate room/corridor-nested areas

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Full DSL suite green: from the dungml root, `uv run pytest packages/dsl/tests/ -q`.
- [ ] Manual smoke: render a small map with `area` nested in a room and confirm the pool draws inside the room and disappears in a fogged view where that room is undiscovered — e.g. `uv run dungml render <file>` (or the existing CLI entrypoint) on a scratch `.dmap`.
