# `party_start` room reference — design spec

Date: 2026-07-04

## Problem

`party_start` currently only accepts world coordinates: `party_start X,Y`. It
stores a `Vec2` on `map.party_start`, drawn as a green "S" disc, and is *purely
a visual marker* — it has no link to the connectivity graph and does not feed
play-sessions. When a play-session is created (backend `sessions.py` or MCP
`server.py`), the starting node (`start_location`, e.g. `room.vault`) is passed
in by the caller, entirely independent of `party_start`.

Authors want to name the starting **room** instead of hand-typing coordinates,
and want that room to become the default start node for new play-sessions so it
auto-reveals on load — tying the authored "where the party begins" to both the
rendered marker and the fog-of-war entry point.

## Current state

- `model.py:531` — `party_start: Optional[Vec2]`.
- `grammar.lark:57` — `party_start_decl: "party_start" NUMBER "," NUMBER`.
- `parser.py:279` — `party_start_decl` → `("party_start", (x, y))`.
- `render/classic_bw.py:486` — `if self.dmap.map.party_start is not None:` →
  `self._party_start(self.dmap.map.party_start)`; `_party_start(pos: Vec2)`
  (line 1350) draws the disc + "S" at a world point.
- `play.py:104-106` — live party tracking overwrites `view.map.party_start`
  with a `Vec2` centroid so the marker follows the party. `node_centroid`
  (`play.py:52`), `_find_room`, `_find_corridor`, `_corridor_centroid` resolve
  a `room.X` / `corridor.Y` node id to a world point; `node_centroid` is
  re-exported from `__init__.py`.
- `play.py` imports the renderer (`from .render import get_renderer`), so the
  renderer **cannot** import `play` — a circular-import constraint. Both
  `play.py` and `render/classic_bw.py` already import `..geometry`.
- Backend `sessions.py:114` `create_session` and MCP `server.py:944`
  `create_session` are two parallel paths that each parse `m.source` to a
  `dmap`, validate the caller's `start_location` against the graph, reveal it,
  and set `party_location`.
- Node id format is `f"{kind}.{name}"` (`room.vault`, `corridor.hall`), matched
  by `graph.has_node(...)`.

## Decisions

- **Room reference with optional coordinate override.** `party_start "vault"`
  names a room (or corridor); optional `at X,Y` overrides where the marker
  draws. Bare `party_start X,Y` stays valid, unchanged.
- **`at` is absolute.** `at X,Y` is an absolute world point (matching how `at`
  works for `marker` / `feature` / `text`). When omitted, the marker draws at
  the named node's centroid.
- **Resolve room first, else corridor.** The name resolves to a `room.<name>`
  if such a room exists, otherwise `corridor.<name>`, otherwise a validation
  error. Both are valid graph nodes and `node_centroid` already handles both.
- **Session default only when unspecified.** A room-referencing `party_start`
  becomes the default `start_location` for new sessions **only** when the
  create call does not pass its own `start_location`. An explicit
  `start_location` always wins. Bare-coords `party_start` contributes no
  default (no node linkage), preserving today's behavior.
- **No bounds-check on `at`.** Parity with today's bare-coords form, which is
  not bounds-checked.
- **No web / draw-tool change.** Preview is server-rendered; the Monaco
  tokenizer already lists `party_start` as a keyword and a following `STRING` /
  `at` needs no new highlighting rule. The click-to-draw tool does not emit
  `party_start`.
- **No `secret` flag, no in-room offset semantics** (YAGNI).

## Design

### 1. Model (`packages/dsl/src/dungml/model.py`)

Introduce a small model and change the field type:

```python
class PartyStart(BaseModel):
    """Where the PCs begin when the map loads. Either a named room/corridor
    (`ref`, resolved to its centroid) and/or an explicit marker point (`at`,
    absolute world coords, overriding the centroid). Bare `party_start X,Y`
    parses to PartyStart(at=(X, Y)) with ref=None (no graph-node linkage)."""
    ref: Optional[str] = None   # room/corridor name as written; None = bare coords
    at: Optional[Vec2] = None   # absolute marker point; overrides ref's centroid
```

`map.party_start` changes from `Optional[Vec2]` to `Optional[PartyStart]`.
Invariant (by construction in the parser): at least one of `ref` / `at` is set.

### 2. Grammar (`packages/dsl/src/dungml/grammar.lark`)

Replace the single rule with two aliased alternatives feeding the same map
property:

```lark
party_start_decl: "party_start" NUMBER "," NUMBER                    -> party_start_coords
                | "party_start" STRING ("at" NUMBER "," NUMBER)?     -> party_start_ref
```

`"at"` is a keyword only in this position; it stays usable as no other token.

### 3. Parser (`packages/dsl/src/dungml/parser.py`)

Replace `party_start_decl` with two transformer methods, each returning the
`("party_start", PartyStart(...))` map-property tuple already consumed at
`parser.py:358`:

```python
def party_start_coords(self, items):
    return ("party_start", PartyStart(at=(_num(items[0]), _num(items[1]))))

def party_start_ref(self, items):
    name = _strip_string(items[0])
    at = None
    if len(items) >= 3:                     # STRING "at" NUMBER "," NUMBER
        at = (_num(items[-2]), _num(items[-1]))
    return ("party_start", PartyStart(ref=name, at=at))
```

### 4. Node resolution (`packages/dsl/src/dungml/geometry.py`)

Relocate `_find_room`, `_find_corridor`, `_corridor_centroid`, and
`node_centroid` from `play.py` into `geometry.py` (both `play` and the renderer
already import `geometry`, breaking the play↔render cycle). `play.py` imports
them back and keeps re-exporting `node_centroid` from `__init__.py` unchanged.

Add two helpers in `geometry.py`:

```python
def party_start_node(dmap) -> Optional[str]:
    """The graph node id a room-referencing party_start points at, or None
    (no ref, or ref matches nothing). Room takes precedence over corridor."""
    ps = dmap.map.party_start
    if ps is None or ps.ref is None:
        return None
    if _find_room(dmap, ps.ref) is not None:
        return f"room.{ps.ref}"
    if _find_corridor(dmap, ps.ref) is not None:
        return f"corridor.{ps.ref}"
    return None

def party_start_point(dmap) -> Optional[Vec2]:
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

### 5. Renderer (`packages/dsl/src/dungml/render/classic_bw.py`)

At line 486, resolve to a point rather than reading the field directly:

```python
pt = party_start_point(self.dmap)
if pt is not None:
    parts.append(self._party_start(pt))
```

`_party_start(pos: Vec2)` is unchanged. `OldSchoolBlue` inherits.

### 6. Live party tracking (`packages/dsl/src/dungml/play.py`)

Line 106 assigns a resolved centroid to the marker so it follows the party.
Update to the new type:

```python
view.map.party_start = PartyStart(at=pos)
```

### 7. Validation (`packages/dsl/src/dungml/validate.py`)

After `known_rooms` / `known_corridors` are computed (~line 69), if
`dmap.map.party_start` has a `ref` that matches neither, emit an error
Diagnostic: `party_start references unknown room/corridor '<ref>'`, anchored to
the map span (`PartyStart` carries no span of its own). No bounds-check on `at`.

### 8. Session default — backend (`packages/backend/src/dungml_backend/routes/sessions.py`)

`create_session` (line 114). `_graph_for` already returns `(dmap, graph)`;
capture the dmap and default the start when the caller omits one:

```python
dmap, graph = _graph_for(m)
...
start = body.start_location
if start is None:
    start = party_start_node(dmap)   # None when no room-ref party_start
if start:
    if not graph.has_node(start):
        raise HTTPException(400, f"unknown start location '{start}'")
    _reveal(graph, start, nodes, doors)
```

The resolved node always exists in the graph (validation guarantees the ref
resolves), so the `has_node` guard stays as-is.

### 9. Session default — MCP (`packages/mcp/src/dungml_mcp/server.py`)

`create_session` (line 944). Mirror the backend: when `start_location is None`,
parse the source and default to `party_start_node(dmap)` before the reveal.
Restructure so the graph is built whenever there is *any* start (caller-given
or defaulted):

```python
start = start_location
dmap = parse(m.source or "")           # wrapped in the existing DmapParseError handling
if start is None:
    start = party_start_node(dmap)
if start is not None:
    g = build_graph(dmap)
    if not g.has_node(start):
        raise ValueError(f"unknown node {start!r} in map")
    _reveal_node(g, start, nodes, doors)
    party = start
```

Update the `create_session` docstring / `start_location` field description to
note that it defaults to the map's `party_start` room when omitted. Also update
the tool summary comment at `server.py:36`.

### 10. Docs

- `docs/dsl-map.md` (`party_start` section ~line 23) — document the room-ref
  and `at` forms and the session-default behavior.
- `docs/dsl-reference.md` (map children table ~line 114 + example ~line 127) —
  update the `party_start` grammar row and example.

## Testing

- **Parser** — `party_start 4,4` → `PartyStart(at=(4,4), ref=None)`;
  `party_start "vault"` → `PartyStart(ref="vault", at=None)`;
  `party_start "vault" at 4,4` → `PartyStart(ref="vault", at=(4,4))`.
- **Resolution** — `party_start_node` returns `room.vault` for a room,
  `corridor.hall` when only a corridor matches, `None` for an unknown ref and
  for a bare-coords start. `party_start_point` returns `at` when set, the
  centroid when only `ref` is set, `None` when neither resolves.
- **Renderer** — the "S" marker renders at the centroid for a room-ref start,
  at `at` when overridden, and (regression) at the point for a bare-coords
  start. Marker absent when the map has no `party_start`.
- **Validation** — unknown `ref` yields exactly one error Diagnostic; a valid
  room ref, a valid corridor ref, and a bare-coords start yield none.
- **Backend session** — creating a session with no `start_location` on a map
  whose `party_start` names a room defaults `party_location` to that node and
  reveals it; an explicit `start_location` still overrides; a bare-coords
  `party_start` leaves the default `None` (parity with today).
- **MCP session** — same defaulting behavior via the MCP `create_session`.
- **Fog regression** — live party tracking still renders the follow marker
  (now via `PartyStart(at=pos)`).
