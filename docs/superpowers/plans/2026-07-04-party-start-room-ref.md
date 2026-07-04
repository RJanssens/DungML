# `party_start` room reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `party_start` name a room/corridor (with an optional `at X,Y` marker override) and make that node the default start location for new play-sessions, while keeping bare `party_start X,Y` working.

**Architecture:** Introduce a `PartyStart` model (`ref` name and/or absolute `at` point) replacing the bare `Vec2` on `MapConfig.party_start`. Node-name→point resolution moves from `play.py` into `geometry.py` (both `play` and the renderer already import `geometry`, avoiding a play↔render import cycle). The renderer resolves a draw point via a new `party_start_point`; both session-create paths (backend + MCP) default their start node via a new `party_start_node` when the caller omits one.

**Tech Stack:** Python 3.14, Pydantic v2 models, Lark grammar/transformer, FastAPI (backend), FastMCP (MCP), pytest.

## Global Constraints

- Bare `party_start X,Y` must keep parsing and rendering exactly as today (regression-protected).
- `at X,Y` is absolute world coordinates (matches `marker`/`feature`/`text` `at`); no bounds-check on it (parity with today's bare form).
- Name resolution: room first (`room.<name>`), else corridor (`corridor.<name>`), else nothing.
- A room-referencing `party_start` supplies a session's default start **only** when the create call omits its own `start_location`; an explicit `start_location` always wins.
- Node id format is `f"{kind}.{name}"` (e.g. `room.vault`, `corridor.hall`).
- No web / draw-tool change; no `secret` flag or in-room offset (out of scope).
- `dungml`'s public API must keep exporting `node_centroid` (currently re-exported in `__init__.py`).

---

### Task 1: Relocate node-resolution helpers to `geometry.py`

Pure refactor, no behavior change. Moves `_find_room`, `_find_corridor`, `_corridor_centroid`, and `node_centroid` out of `play.py` (which imports the renderer) into `geometry.py` (which the renderer imports), so later tasks can resolve a room name to a point inside the renderer without a circular import.

**Files:**
- Modify: `packages/dsl/src/dungml/geometry.py` (typing/model imports near lines 13–27; append functions at end)
- Modify: `packages/dsl/src/dungml/play.py:10-65` (drop the four functions; fix imports)
- Test: `packages/dsl/tests/test_play.py` (existing suite is the regression guard)

**Interfaces:**
- Consumes: existing `room_polygon` (`geometry.py:266`), `_centroid` (`geometry.py:379`).
- Produces: `geometry.node_centroid(dmap: DungeonMap, node_id: str) -> Optional[Vec2]`, plus module-private `_find_room`, `_find_corridor`, `_corridor_centroid` — same signatures they had in `play.py`. `play.node_centroid` remains importable (re-exported).

- [ ] **Step 1: Run the existing play tests to confirm a green baseline**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/dsl/tests/test_play.py -q`
Expected: PASS (all).

- [ ] **Step 2: Add the two needed imports to `geometry.py`**

Change the typing import (line 13) from:

```python
from typing import Union
```

to:

```python
from typing import Optional, Union
```

Add `DungeonMap` to the `from .model import (...)` block (the block already imports `Corridor`, `LineSegment`, `Room`, `Vec2`). After editing, the block reads:

```python
from .model import (
    ArcEdge,
    ArcSegment,
    BoundaryRoom,
    CircleRoom,
    Corridor,
    DungeonMap,
    LineEdge,
    LineSegment,
    PolygonRoom,
    RectRoom,
    Room,
    Vec2,
)
```

- [ ] **Step 3: Append the four functions to the end of `geometry.py`**

```python
def _find_room(dmap: DungeonMap, name: str) -> Optional[Room]:
    room = dmap.rooms.get(name)
    if room is not None:
        return room
    for layer in dmap.layers:
        for r in layer.rooms:
            if r.name == name:
                return r
    return None


def _find_corridor(dmap: DungeonMap, name: str) -> Optional[Corridor]:
    corr = dmap.corridors.get(name)
    if corr is not None:
        return corr
    for layer in dmap.layers:
        for c in layer.corridors:
            if c.name == name:
                return c
    return None


def _corridor_centroid(c: Corridor) -> Optional[Vec2]:
    pts: list[Vec2] = list(c.nodes.values())
    if not pts:
        for s in c.segments:
            if isinstance(s, LineSegment):
                pts.append(s.start)
                pts.append(s.end)
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def node_centroid(dmap: DungeonMap, node_id: str) -> Optional[Vec2]:
    """A representative interior point for a `room.X` / `corridor.Y` node,
    used to place the party marker. None if the node can't be located."""
    kind, _, name = node_id.partition(".")
    if kind == "room":
        room = _find_room(dmap, name)
        if room is None:
            return None
        poly = room_polygon(room)
        return _centroid(poly) if poly else None
    if kind == "corridor":
        corr = _find_corridor(dmap, name)
        return _corridor_centroid(corr) if corr is not None else None
    return None
```

- [ ] **Step 4: Remove the four functions from `play.py` and fix its imports**

Delete `_find_room`, `_find_corridor`, `_corridor_centroid`, and `node_centroid` (currently `play.py:18-65`).

Replace the import block (`play.py:12-14`):

```python
from .geometry import _centroid, room_polygon
from .graph import Graph, fog_of_war
from .model import Corridor, DungeonMap, LineSegment, Room, Vec2
```

with (drop the now-unused `_centroid`, `room_polygon`, `Corridor`, `LineSegment`, `Room`, `Vec2`; import `node_centroid` from geometry so `play.node_centroid` still resolves):

```python
from .geometry import node_centroid
from .graph import Graph, fog_of_war
from .model import DungeonMap
```

(`render_fogged` still uses `DungeonMap`, `Iterable`, `Optional`, `fog_of_war`, `get_renderer`, `node_centroid` — all still imported. `play.py:106` still assigns a `Vec2` to `party_start`; that changes in Task 2.)

- [ ] **Step 5: Run the DSL suite to confirm nothing broke**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/dsl/tests -q`
Expected: PASS (all). `from dungml import node_centroid` and `from dungml.play import node_centroid` both still resolve (play re-exports it).

- [ ] **Step 6: Commit**

```bash
cd /home/raf/roleplaying/dungml
git add packages/dsl/src/dungml/geometry.py packages/dsl/src/dungml/play.py
git commit -m "refactor(dsl): move node-resolution helpers to geometry"
```

---

### Task 2: `PartyStart` model, parsing both forms, rendering, and follow-marker

The atomic type flip: `MapConfig.party_start` becomes `Optional[PartyStart]`. Because that single type change touches the producer (parser), the store (model), and both consumers (renderer, live follow-marker in `play.py`), they change together so the suite is green at the task boundary.

**Files:**
- Modify: `packages/dsl/src/dungml/model.py` (add `PartyStart` before `MapConfig` at line 507; change field at line 531)
- Modify: `packages/dsl/src/dungml/grammar.lark:57`
- Modify: `packages/dsl/src/dungml/parser.py` (add `PartyStart` to model import; replace `party_start_decl`, `parser.py:279-280`)
- Modify: `packages/dsl/src/dungml/geometry.py` (append `party_start_node`, `party_start_point`)
- Modify: `packages/dsl/src/dungml/render/classic_bw.py` (import `party_start_point`; change lines 486-487)
- Modify: `packages/dsl/src/dungml/play.py:106` (assign `PartyStart(at=pos)`; import `PartyStart`)
- Modify: `packages/dsl/src/dungml/__init__.py` (export `party_start_node`)
- Test: `packages/dsl/tests/test_parser.py`, `packages/dsl/tests/test_render_classic.py`, `packages/dsl/tests/test_play.py`

**Interfaces:**
- Consumes: `geometry.node_centroid`, `geometry._find_room`, `geometry._find_corridor` (Task 1).
- Produces:
  - `model.PartyStart(ref: Optional[str] = None, at: Optional[Vec2] = None)`
  - `geometry.party_start_node(dmap: DungeonMap) -> Optional[str]`
  - `geometry.party_start_point(dmap: DungeonMap) -> Optional[Vec2]`
  - `dungml.party_start_node` (re-export, consumed by Tasks 4 & 5)

- [ ] **Step 1: Write the failing parser tests**

Add to `packages/dsl/tests/test_parser.py`:

```python
def test_party_start_bare_coords():
    from dungml import parse
    from dungml.model import PartyStart
    m = parse('map "M" { grid { bounds 10 x 10 } party_start 4,5 }')
    assert m.map.party_start == PartyStart(ref=None, at=(4.0, 5.0))


def test_party_start_room_ref():
    from dungml import parse
    from dungml.model import PartyStart
    m = parse(
        'map "M" { grid { bounds 10 x 10 } party_start "vault" }\n'
        'room "vault" { rect 0,0 4 x 4 }'
    )
    assert m.map.party_start == PartyStart(ref="vault", at=None)


def test_party_start_room_ref_with_at():
    from dungml import parse
    from dungml.model import PartyStart
    m = parse(
        'map "M" { grid { bounds 10 x 10 } party_start "vault" at 2,3 }\n'
        'room "vault" { rect 0,0 4 x 4 }'
    )
    assert m.map.party_start == PartyStart(ref="vault", at=(2.0, 3.0))
```

- [ ] **Step 2: Run the parser tests to verify they fail**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/dsl/tests/test_parser.py -k party_start -q`
Expected: FAIL — `ImportError: cannot import name 'PartyStart'` (and grammar/transformer not yet updated).

- [ ] **Step 3: Add the `PartyStart` model and change the field type**

In `packages/dsl/src/dungml/model.py`, immediately before `class MapConfig(BaseModel):` (line 507), add:

```python
class PartyStart(BaseModel):
    """Where the PCs begin when the map loads. `ref` names a room/corridor
    (resolved to its centroid); `at` is an explicit marker point (absolute
    world coords) that overrides the centroid. Bare `party_start X,Y` parses
    to `PartyStart(at=(X, Y))` with `ref=None` (no graph-node linkage)."""
    ref: Optional[str] = None
    at: Optional[Vec2] = None
```

Change line 531 from:

```python
    party_start: Optional[Vec2] = None
```

to:

```python
    party_start: Optional[PartyStart] = None
```

(`Optional` and `Vec2` are already imported in `model.py`; `BaseModel` is the base class already in use.)

- [ ] **Step 4: Update the grammar**

In `packages/dsl/src/dungml/grammar.lark`, replace line 57:

```lark
party_start_decl: "party_start" NUMBER "," NUMBER
```

with:

```lark
party_start_decl: "party_start" (NUMBER "," NUMBER | STRING ("at" NUMBER "," NUMBER)?)
```

- [ ] **Step 5: Update the parser transformer**

In `packages/dsl/src/dungml/parser.py`, add `PartyStart` to the `from .model import (...)` block (alphabetically near `MapConfig`, line 45). Then replace the `party_start_decl` method (lines 279-280):

```python
    def party_start_decl(self, items: list[Any]) -> tuple[str, Any]:
        return ("party_start", (_num(items[0]), _num(items[1])))
```

with:

```python
    def party_start_decl(self, items: list[Any]) -> tuple[str, Any]:
        first = items[0]
        if isinstance(first, Token) and first.type == "STRING":
            name = _strip_string(first)
            at = (_num(items[1]), _num(items[2])) if len(items) == 3 else None
            return ("party_start", PartyStart(ref=name, at=at))
        return ("party_start", PartyStart(at=(_num(items[0]), _num(items[1]))))
```

(`Token` is already imported at `parser.py:17`; `_num`/`_strip_string` exist. `map_block` at `parser.py:358` already assigns `party_start = val`, so the map-assembly code needs no change.)

- [ ] **Step 6: Run the parser tests to verify they pass**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/dsl/tests/test_parser.py -k party_start -q`
Expected: PASS (3 tests).

- [ ] **Step 7: Write the failing renderer + follow-marker tests**

Add to `packages/dsl/tests/test_render_classic.py`:

```python
def test_party_start_ref_renders_marker_at_centroid():
    from dungml import parse, render
    svg = render(parse(
        'map "M" { grid { bounds 20 x 20 } party_start "vault" }\n'
        'room "vault" { rect 0,0 4 x 4 }'
    ))
    # room centre is (2,2) in world units; the marker group is emitted.
    assert 'class="party-start"' in svg


def test_party_start_at_overrides_centroid():
    from dungml import parse, render
    svg = render(parse(
        'map "M" { grid { bounds 20 x 20 } party_start "vault" at 6,7 }\n'
        'room "vault" { rect 0,0 4 x 4 }'
    ))
    assert 'class="party-start"' in svg
    assert 'cx="6"' in svg  # marker forced to the `at` x, not the centroid (2)


def test_party_start_absent_when_unset():
    from dungml import parse, render
    svg = render(parse('map "M" { grid { bounds 20 x 20 } }'))
    assert 'class="party-start"' not in svg
```

Add to `packages/dsl/tests/test_play.py`:

```python
def test_follow_marker_renders_at_party_location():
    from dungml import parse, render_fogged
    src = (
        'map "M" { grid { bounds 20 x 20 } }\n'
        'room "a" { rect 0,0 4 x 4 }'
    )
    svg = render_fogged(parse(src), ["room.a"], [], party_location="room.a")
    assert 'class="party-start"' in svg
```

Add to `packages/dsl/tests/test_geometry.py`:

```python
def test_party_start_node_prefers_room_then_corridor():
    from dungml import parse
    from dungml.geometry import party_start_node, party_start_point
    room_ref = parse(
        'map "M" { grid { bounds 20 x 20 } party_start "vault" }\n'
        'room "vault" { rect 0,0 4 x 4 }'
    )
    assert party_start_node(room_ref) == "room.vault"
    assert party_start_point(room_ref) == (2.0, 2.0)  # rect centroid

    corr_ref = parse(
        'map "M" { grid { bounds 20 x 20 } party_start "hall" }\n'
        'corridor "hall" { width 1 node n1 at 8,1 node n2 at 12,1 run n1 to n2 }'
    )
    assert party_start_node(corr_ref) == "corridor.hall"


def test_party_start_node_none_for_coords_and_unknown():
    from dungml import parse
    from dungml.geometry import party_start_node, party_start_point
    coords = parse('map "M" { grid { bounds 20 x 20 } party_start 3,4 }')
    assert party_start_node(coords) is None
    assert party_start_point(coords) == (3.0, 4.0)  # `at` wins

    unknown = parse(
        'map "M" { grid { bounds 20 x 20 } party_start "ghost" }\n'
        'room "vault" { rect 0,0 4 x 4 }'
    )
    assert party_start_node(unknown) is None
    assert party_start_point(unknown) is None
```

- [ ] **Step 8: Run these tests to verify they fail**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/dsl/tests/test_render_classic.py -k party_start packages/dsl/tests/test_play.py::test_follow_marker_renders_at_party_location -q`
Expected: FAIL — renderer still passes a `PartyStart` to `_party_start(pos: Vec2)` (unpacking error), and `play.py:106` assigns a raw `Vec2` that no longer matches the field type.

- [ ] **Step 9: Add the resolution helpers to `geometry.py`**

Append to `packages/dsl/src/dungml/geometry.py`:

```python
def party_start_node(dmap: DungeonMap) -> Optional[str]:
    """The graph node id a room-referencing `party_start` points at, or None
    (no ref, or ref matches nothing). Room takes precedence over corridor."""
    ps = dmap.map.party_start
    if ps is None or ps.ref is None:
        return None
    if _find_room(dmap, ps.ref) is not None:
        return f"room.{ps.ref}"
    if _find_corridor(dmap, ps.ref) is not None:
        return f"corridor.{ps.ref}"
    return None


def party_start_point(dmap: DungeonMap) -> Optional[Vec2]:
    """Where the start marker draws: explicit `at`, else the ref's centroid,
    else None (nothing to draw)."""
    ps = dmap.map.party_start
    if ps is None:
        return None
    if ps.at is not None:
        return ps.at
    node = party_start_node(dmap)
    return node_centroid(dmap, node) if node else None
```

- [ ] **Step 10: Update the renderer to resolve a point**

In `packages/dsl/src/dungml/render/classic_bw.py`, add `party_start_point` to the `from ..geometry import (...)` block (line 14). Then replace lines 486-487:

```python
        if self.dmap.map.party_start is not None:
            parts.append(self._party_start(self.dmap.map.party_start))
```

with:

```python
        pt = party_start_point(self.dmap)
        if pt is not None:
            parts.append(self._party_start(pt))
```

(`_party_start(pos: Vec2)` is unchanged; `OldSchoolBlue` inherits this method.)

- [ ] **Step 11: Update the live follow-marker in `play.py`**

Add `PartyStart` to the model import (`play.py` now reads `from .model import DungeonMap, PartyStart`). Change `play.py:106` from:

```python
            view.map.party_start = pos
```

to:

```python
            view.map.party_start = PartyStart(at=pos)
```

- [ ] **Step 12: Export `party_start_node` from the package**

In `packages/dsl/src/dungml/__init__.py`, after the `from .play import ...` line (line 18) add:

```python
from .geometry import party_start_node
```

and add `"party_start_node",` to the `__all__` list (near `"node_centroid",`, line 87).

- [ ] **Step 13: Run the full DSL suite**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/dsl/tests -q`
Expected: PASS (all — new parser, render, and follow-marker tests included; bare-coords regression tests still green).

- [ ] **Step 14: Commit**

```bash
cd /home/raf/roleplaying/dungml
git add packages/dsl/src/dungml/model.py packages/dsl/src/dungml/grammar.lark \
  packages/dsl/src/dungml/parser.py packages/dsl/src/dungml/geometry.py \
  packages/dsl/src/dungml/render/classic_bw.py packages/dsl/src/dungml/play.py \
  packages/dsl/src/dungml/__init__.py packages/dsl/tests/test_parser.py \
  packages/dsl/tests/test_render_classic.py packages/dsl/tests/test_play.py \
  packages/dsl/tests/test_geometry.py
git commit -m "feat(dsl): party_start accepts a room/corridor ref with optional at-override"
```

---

### Task 3: Validate unknown `party_start` ref

Emit an error diagnostic when `party_start`'s `ref` matches no room or corridor.

**Files:**
- Modify: `packages/dsl/src/dungml/validate.py` (after `known_corridors`, ~line 70)
- Test: `packages/dsl/tests/test_validate.py`

**Interfaces:**
- Consumes: `known_rooms`, `known_corridors` sets (`validate.py:69-70`); `_diag(level, msg, span)` helper (`validate.py:47`); `dmap.map.span`, `dmap.map.party_start`.
- Produces: no new symbols.

- [ ] **Step 1: Write the failing validation tests**

Add to `packages/dsl/tests/test_validate.py`:

```python
def test_party_start_unknown_ref_errors():
    from dungml import parse, validate
    diags = validate(parse(
        'map "M" { grid { bounds 10 x 10 } party_start "ghost" }\n'
        'room "vault" { rect 0,0 4 x 4 }'
    ))
    msgs = [d.message for d in diags if d.level == "error"]
    assert any("party_start" in m and "ghost" in m for m in msgs)


def test_party_start_valid_refs_and_coords_ok():
    from dungml import parse, validate
    # room ref, corridor ref, and bare coords each produce no party_start error.
    for ps in ('party_start "vault"', 'party_start "hall"', "party_start 1,1"):
        src = (
            f'map "M" {{ grid {{ bounds 20 x 20 }} {ps} }}\n'
            'room "vault" { rect 0,0 4 x 4 }\n'
            'corridor "hall" { width 1 node n1 at 8,1 node n2 at 12,1 run n1 to n2 }'
        )
        diags = validate(parse(src))
        assert not [d for d in diags if "party_start" in d.message], ps
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/dsl/tests/test_validate.py -k party_start -q`
Expected: FAIL — `test_party_start_unknown_ref_errors` finds no such error.

- [ ] **Step 3: Add the validation check**

In `packages/dsl/src/dungml/validate.py`, immediately after the `known_corridors = set(dmap.corridors.keys())` line (line 70), add:

```python
    ps = dmap.map.party_start
    if ps is not None and ps.ref is not None:
        if ps.ref not in known_rooms and ps.ref not in known_corridors:
            diags.append(
                _diag(
                    "error",
                    f"party_start references unknown room/corridor '{ps.ref}'",
                    dmap.map.span,
                )
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/dsl/tests/test_validate.py -k party_start -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/raf/roleplaying/dungml
git add packages/dsl/src/dungml/validate.py packages/dsl/tests/test_validate.py
git commit -m "feat(dsl): validate party_start ref resolves to a room/corridor"
```

---

### Task 4: Backend session default from `party_start`

When `create_session` is called without a `start_location`, default it to the map's `party_start` node.

**Files:**
- Modify: `packages/backend/src/dungml_backend/routes/sessions.py` (import; `create_session`, lines 114-137)
- Test: `packages/backend/tests/test_sessions.py`

**Interfaces:**
- Consumes: `dungml.party_start_node` (Task 2); `_graph_for(m) -> (dmap, graph)` (`sessions.py:60`); `_reveal(graph, node, nodes, doors)` (`sessions.py:71`).
- Produces: no new symbols.

- [ ] **Step 1: Write the failing backend tests**

Add to `packages/backend/tests/test_sessions.py`:

```python
PARTY_START_MAP = """
map "M" { grid { cell 20 px bounds 30 x 30 } renderer "classic-bw" party_start "a" }
room "a" { rect 0,0 6 x 6 label "A" }
room "b" { rect 12,0 6 x 6 label "B" }
corridor "c1" { width 1 node n1 at 6,3 node n2 at 12,3 run n1 to n2 }
door at 6,3 { connects room.a, corridor.c1 type wooden }
door at 12,3 { connects corridor.c1, room.b type wooden }
"""


@pytest.fixture
def ps_map_id(auth_client) -> str:
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    r = auth_client.post(
        f"/api/projects/{pid}/maps", json={"name": "M", "source": PARTY_START_MAP}
    )
    return r.json()["id"]


def test_create_session_defaults_to_party_start(auth_client, ps_map_id):
    r = auth_client.post(
        f"/api/maps/{ps_map_id}/sessions", json={"name": "Run"}
    )
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["party_location"] == "room.a"
    assert "room.a" in s["discovered_nodes"]


def test_explicit_start_overrides_party_start(auth_client, ps_map_id):
    r = auth_client.post(
        f"/api/maps/{ps_map_id}/sessions",
        json={"name": "Run", "start_location": "room.b"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["party_location"] == "room.b"
```

Also confirm the existing behavior stays intact: the `MAP_SRC` map (no `party_start`) must still create a session with `party_location` null when no start is given — add:

```python
def test_no_party_start_leaves_location_unset(auth_client, map_id):
    r = auth_client.post(f"/api/maps/{map_id}/sessions", json={"name": "Run"})
    assert r.status_code == 201, r.text
    assert r.json()["party_location"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/backend/tests/test_sessions.py -k "party_start or unset" -q`
Expected: FAIL — `test_create_session_defaults_to_party_start` gets `party_location` null (no defaulting yet). (`test_no_party_start_leaves_location_unset` passes already — it guards against regression.)

- [ ] **Step 3: Add the import**

In `packages/backend/src/dungml_backend/routes/sessions.py`, add `party_start_node` to the `from dungml import (...)` block (lines 13-19), keeping it alphabetical:

```python
from dungml import (
    build_graph,
    is_blocked,
    parse,
    party_start_node,
    render_fogged,
    visible_doors,
)
```

- [ ] **Step 4: Default the start node in `create_session`**

Replace the head of `create_session` (`sessions.py:115-126`):

```python
def create_session(map_id: str, body: SessionCreateIn, user: CurrentUser, db: DbDep):
    m = _get_owned_map(db, map_id, user)
    _, graph = _graph_for(m)
    nodes: set[str] = set()
    doors: set[str] = set()
    start = body.start_location
    if start:
        if not graph.has_node(start):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"unknown start location '{start}'"
            )
        _reveal(graph, start, nodes, doors)
```

with (capture the dmap; default the start when the caller omits one):

```python
def create_session(map_id: str, body: SessionCreateIn, user: CurrentUser, db: DbDep):
    m = _get_owned_map(db, map_id, user)
    dmap, graph = _graph_for(m)
    nodes: set[str] = set()
    doors: set[str] = set()
    start = body.start_location
    if start is None:
        start = party_start_node(dmap)
    if start:
        if not graph.has_node(start):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"unknown start location '{start}'"
            )
        _reveal(graph, start, nodes, doors)
```

(The rest of the function — building `PlaySession(party_location=start, ...)` — is unchanged. A defaulted node always exists in the graph, so the `has_node` guard is safe.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/backend/tests/test_sessions.py -q`
Expected: PASS (all — new tests plus the existing session-route suite).

- [ ] **Step 6: Commit**

```bash
cd /home/raf/roleplaying/dungml
git add packages/backend/src/dungml_backend/routes/sessions.py packages/backend/tests/test_sessions.py
git commit -m "feat(backend): default new session start to the map's party_start"
```

---

### Task 5: MCP session default from `party_start`

Mirror Task 4 in the MCP `create_session` tool.

**Files:**
- Modify: `packages/mcp/src/dungml_mcp/server.py` (import; `create_session`, lines 944-983; tool summary comment line 36)
- Test: `packages/mcp/tests/test_server.py`

**Interfaces:**
- Consumes: `dungml.party_start_node` (Task 2); `parse`, `build_graph`, `DmapParseError`, `_reveal_node` (already in `server.py`).
- Produces: no new symbols.

- [ ] **Step 1: Write the failing MCP tests**

Add to `packages/mcp/tests/test_server.py` (the `fresh_db` fixture and the `_SESSION_MAP` / `session_map` pattern already exist in this file — mirror them):

```python
_PARTY_START_MAP = """
map "Dungeon" { grid { bounds 60 x 40 } party_start "antechamber" }
room "antechamber" { rect 2,4 12 x 10 label "Ante" }
room "sanctum"     { rect 18,4 10 x 10 label "Sanctum" }
corridor "passage" { width 2 segment line from 14,9 to 18,9 }
door at 14,9 { connects room.antechamber, corridor.passage }
"""


@pytest.fixture
def party_start_map(fresh_db):
    s = fresh_db
    p = s.create_project(name="PS")
    m = s.create_map(project_id=p["id"], name="Dungeon", source=_PARTY_START_MAP)
    return s, m["id"]


def test_create_session_defaults_to_party_start(party_start_map):
    s, mid = party_start_map
    sess = s.create_session(map_id=mid, name="Party")
    assert sess["party_location"] == "room.antechamber"
    assert "room.antechamber" in sess["discovered_nodes"]


def test_create_session_explicit_start_overrides_party_start(party_start_map):
    s, mid = party_start_map
    sess = s.create_session(map_id=mid, name="Party", start_location="room.sanctum")
    assert sess["party_location"] == "room.sanctum"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/mcp/tests/test_server.py -k "defaults_to_party_start or overrides_party_start" -q`
Expected: FAIL — `party_location` is null (no defaulting yet).

- [ ] **Step 3: Add the import**

In `packages/mcp/src/dungml_mcp/server.py`, add `party_start_node` to the `from dungml import (...)` block (lines 70-83), keeping it ordered near `parse`:

```python
    parse,
    party_start_node,
    validate as dsl_validate,
```

- [ ] **Step 4: Default the start node in the MCP `create_session`**

Replace the body of `create_session` from `nodes: set[str] = set()` through `party = start_location` (`server.py:960-971`):

```python
        nodes: set[str] = set()
        doors: set[str] = set()
        party = None
        if start_location is not None:
            try:
                g = build_graph(parse(m.source or ""))
            except DmapParseError as e:
                raise ValueError(f"map source has a parse error: {e}") from e
            if not g.has_node(start_location):
                raise ValueError(f"unknown node {start_location!r} in map")
            _reveal_node(g, start_location, nodes, doors)
            party = start_location
```

with (parse once; default the start from `party_start` when the caller omits one):

```python
        nodes: set[str] = set()
        doors: set[str] = set()
        party = None
        try:
            dmap = parse(m.source or "")
        except DmapParseError as e:
            raise ValueError(f"map source has a parse error: {e}") from e
        start = start_location if start_location is not None else party_start_node(dmap)
        if start is not None:
            g = build_graph(dmap)
            if not g.has_node(start):
                raise ValueError(f"unknown node {start!r} in map")
            _reveal_node(g, start, nodes, doors)
            party = start
```

- [ ] **Step 5: Update the `start_location` field description and tool summary**

In the `start_location` `Field(description=...)` (`server.py:951-952`), append a sentence:

```python
            description="Optional starting node ('room.NAME' or 'corridor.NAME'); "
            "marked discovered and set as the party location. Defaults to the "
            "map's party_start room when omitted.",
```

Update the tool-summary comment at `server.py:36`:

```python
- `create_session(map_id, name, start_location?)`     → new session (start defaults to map party_start)
```

- [ ] **Step 6: Run the MCP suite**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/mcp/tests/test_server.py -q`
Expected: PASS (all — new tests plus the existing session tests, including `test_create_session_rejects_unknown_start`).

- [ ] **Step 7: Commit**

```bash
cd /home/raf/roleplaying/dungml
git add packages/mcp/src/dungml_mcp/server.py packages/mcp/tests/test_server.py
git commit -m "feat(mcp): default new session start to the map's party_start"
```

---

### Task 6: Documentation

Update the DSL docs to describe the new forms and the session-default behavior.

**Files:**
- Modify: `docs/dsl-map.md` (`party_start` section, ~lines 19-27)
- Modify: `docs/dsl-reference.md` (map children table ~line 114; example ~line 127)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `docs/dsl-map.md`**

Replace the `party_start` description (the `### party_start` block, ~lines 23-27) with:

```markdown
### `party_start`

`party_start` (optional) marks where the characters begin when the map loads.
It's drawn as a green **S** marker and, when it names a room/corridor, becomes
the default party location for new play-sessions (auto-revealed on load; an
explicit start passed to session-create overrides it).

Three forms:

- `party_start X,Y` — a bare marker at a world cell (no session linkage).
- `party_start "name"` — a room (or, failing that, corridor) named `name`; the
  marker is drawn at its centroid.
- `party_start "name" at X,Y` — as above, but the marker is forced to the
  absolute cell `X,Y` instead of the centroid.
```

Update the header comment example (~line 19) so it shows a room ref:

```markdown
  party_start "entry_hall"   # optional: room the PCs begin in on load
```

- [ ] **Step 2: Update `docs/dsl-reference.md`**

Change the `party_start` row in the map children table (line 114) from:

```markdown
| `party_start NUMBER,NUMBER` | Where the PCs begin when the map loads. |
```

to:

```markdown
| `party_start NUMBER,NUMBER` | Marker at a world cell. |
| `party_start STRING [at NUMBER,NUMBER]` | Party begins in room/corridor `STRING` (marker at its centroid, or the `at` cell). Becomes a new session's default start node. |
```

Update the example near line 127 from `party_start 2,18` to a room-ref form consistent with the surrounding example's room names, e.g.:

```dmap
  party_start "gatehouse"
```

(Pick a room name that actually exists in that example block; if `2,18` sat inside a specific room there, use that room's name.)

- [ ] **Step 3: Commit**

```bash
cd /home/raf/roleplaying/dungml
git add docs/dsl-map.md docs/dsl-reference.md
git commit -m "docs(dsl): document party_start room reference and session default"
```

---

## Notes for the implementer

- Run `uv run pytest` from the repo root; each package's tests live under `packages/<pkg>/tests`.
- Tasks 1→2 are ordered (Task 2 needs the moved helpers). Tasks 3, 4, 5, 6 each depend on Task 2 (the `PartyStart` type and `party_start_node` export) but are independent of each other.
- The suite must be green at every task boundary. Within Task 2 the intermediate steps intentionally go red (the type flip is atomic across model/parser/renderer/play).
