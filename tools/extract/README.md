# Converting a map page to DungML

`tools/extract/` turns a scanned or rendered **gridded dungeon map page**, plus
the module text that keys it, into a `.dmap` that plays correctly: rooms,
caves, corridors, doors, features, read-aloud text and GM notes, with fog of
war revealing it the way a party would expect.

It works as a split between code and a reader:

- **Code** does everything that has to be exact: the grid, which cells are
  floor, where labels and door symbols are, outlines, connections.
- **A reader** (you, or Claude via `/convert-map`) does what needs judgement,
  and writes it down in the job folder: what each label says, what the
  symbols the templates don't know mean, how a room's key text splits into
  "what the party sees" and "what only the GM knows".

Nothing is eyeballed into coordinates. The first attempt at this
(`extract/73_nw.dmap`, a model reading positions off an ASCII grid) produced a
map that barely resembled the page; the pipeline exists because of it.

**Works for:** maps drawn on a square grid, rooms and corridors on grid lines,
caves as irregular blobs, door symbols on grid lines — the one-page-dungeon
style of Stonehell. Other cartography needs a new style kit (below).

## Quick start

```bash
# once: the Python deps the steps use (on top of the dungml workspace)
DEPS="--with pillow --with numpy --with scipy --with scikit-image --with cairosvg"

uv run $DEPS python tools/extract/convert.py prep    JOB   # grid, labels sheet
#   → read JOB/work/labels_sheet.png, write JOB/labels.json
uv run $DEPS python tools/extract/convert.py all     JOB   # symbols → … → party
uv run $DEPS python tools/extract/convert.py upload  JOB   # onto a dmap-server project
```

In Claude Code, `/convert-map <job folder or page image>` walks all of it.

## The job folder

One folder per map page. Everything a reader decides lives here, so a re-run
reproduces the map; `work/` is scratch and can be deleted.

| File | Who writes it | What |
|---|---|---|
| `job.json` | reader | page image, style, map name/title, reference map, party walk, upload target |
| `labels.json` | reader | text of every label box, in the order of `work/labels_sheet.png` (`"-"` for a box that isn't a label) |
| `corrections.json` | reader | everything the code can't know — see below; each entry is a counted correction |
| `key.json` | reader | where the module text keys this map, and the split overrides |
| `descriptions.json` | `describe` | room / feature / trap text, split into description and dm_notes |
| `<name>.dmap` | `build` | the map |
| `work/` | steps | grid, masks, sheets, `symbols_dbg.png`, `diff.png`, `score.json`, `party/` |

### `job.json`

```json
{
 "name": "1A",
 "title": "Stonehell 1A — Hell's Antechamber",
 "image": "../../../1657893409500/73.jpg",
 "style": "stonehell",
 "reference": "../../module/maps/_1A.dmap",
 "door_text": {"arch": "A", "portcullis": "B"},
 "party": {"start": "1", "open": ["5.5,18"], "reveal_secret": ["7,25.5"]},
 "upload": {"project": "<project id>", "map": "1A auto-extracted"}
}
```

Paths are relative to the job folder. `grid` (`{"cells": 30}` or
`{"pitch": 30.07}`) overrides grid detection. `includes` defaults to
`["core.dmap"]`. `door_text` gives a door type the text of a features-key
entry (`"arch": "A"`) or a legend entry (`"portcullis": "traps.Portcullis"`).
`label_rooms` lists label texts that mark many rooms sharing one key entry
(`["Cpt", "UCpt"]`: each instance becomes a room, `Cpt1`, `Cpt2`…).
`reference` is an existing hand-made map to compare with. `party` configures
the walk (see *Party-view check*). `expected_warnings` is where each
validation warning that isn't a defect is explained (see *Warnings*).

### `maps.json` (one per module, next to the job folders)

Every level an exit can target: its id (`1A`, `2B`…), its **project map
name** — which is what DungML `exit … to "NAME"` resolves — and whether it's a
placeholder. `upload` names each converted map after its entry and creates any
missing placeholder, so every exit resolves today and keeps resolving when the
placeholder is replaced by the real conversion (same name).

### `corrections.json`

The code's output plus these is the map. Keep a `_why` entry explaining each
one — it's the record of what the DSL, libraries or templates couldn't do.

| Key | Shape | Use for |
|---|---|---|
| `retype` | `[{pos, type, state?, from?}]` | a detected door (or open connection) at `pos` is really `one-way` (with `from` = the cell it opens from), `stone`, `portcullis`, `locked`… |
| `extra_doors` | `[{edges, pos, type, state?}]` | a door the templates missed (`edges`: `[[[i,j],[i,j]]]` lattice edges it sits on) |
| `walls` | `[[[i,j],[i,j]]]` | a wall drawn between two floor cells |
| `room_rect` | `{"27": [i0, j0, i1, j1]}` | force a room's cells |
| `extra_rooms` | `{"27a": [[i, j]]}` | an unlabelled space that is a room (crypt niches) |
| `label_cell` | `{"12": [i, j]}` / `{"Dom": [[i, j], …]}` | a label printed outside its room; for a `label_rooms` label, more instances prep's label boxes missed |
| `room_poly` | `{"12": [[x, y], …]}` | the room's outline, where the page's shape isn't a cell staircase (a triangle cut by a drawn diagonal wall) |
| `not_floor` | `[[i, j]]` | white art that isn't floor |
| `floor` | `[[i, j]]` | a cell that is floor though under the floor threshold (a corner breach) |
| `features` | `[{type, at, scale?, rotate?, description?, dm_notes?}]` | icons, at cell precision; `description`/`dm_notes` may be literal text or a reference `"features_key.C"` / `"traps.Pit"` / `"stalls.G"` into `descriptions.json` |
| `exits` | `[{at, to, land?, label?, secret?, description?, dm_notes?}]` | a way to another map: `to` is a level id from `maps.json`, `land` the point on that map (default its centre). Teleports are exits too, even to the same map |
| `region_notes` | `[{cell, description?, dm_notes?}]` | text for the space holding a cell (a lettered feature with no icon, an exit stub) |
| `not_doors` | `[{at, type?}]` | drop a symbol false positive near a point (only of `type`, if given) |
| `not_walls` | `[[[i,j],[i,j]]]` | an edge the wall detector took for a wall (icon outlines touching rock) |
| `not_cave` / `cave` | `["17"]` | a label the cave test got wrong (icon line-work looks organic; a cave label in a flat pocket) |
| `dots` / `not_dots` | `false` / `[[x, y]]` | turn pillar-dot detection off, or drop one |
| `room_style` | `{"canyon": ["allow_overlap"], "6": ["line_style ruined"]}` | DSL lines for one room (by label or `extra_rooms` name): ruined walls, open ground that ruins stand on |
| `not_circles` / `not_bands` | `[[x, y]]` | drop a round room / slanted passage the vector pass found at (or through) a point |

Coordinates: cells are `[row, col]`; door and feature positions are map
units `[x, y]` (a door on a cell edge is `x.5` or an integer on the line).

### `key.json`

See the docstring of `describe.py`. It names the key sheet (`sheet`), the
markers around the room key, features key, legend and wandering-monster
table, the overview paragraphs that become the map description, and:

- `desc_sentences` — rooms where the split rule is wrong, as sentence
  indices that are read-aloud, **with the reason**. Review every entry the
  rule produced; the rule is "perceivable first, GM material after", which
  one-page keys mostly follow.
- `extras` — tables and notes folded into a room's dm_notes.

## Steps

| Step | Reads | Writes | Check |
|---|---|---|---|
| `prep` | page | grid, masks, `boxes.json`, `labels_sheet.png` | grid size printed matches the page |
| `symbols` | `notext.png` + style templates | `symbols.json`, `symbols_dbg.png` | every symbol on the page circled, nothing else |
| `describe` | module text + `key.json` | `descriptions.json` | review the description/dm_notes split |
| `build` | all of the above | `<name>.dmap` | every label has a room ("labels without a room" is empty) |
| `score` | map + page (+ reference) | `score.json`, `diff.png` | IoU ≳ 0.9; 0 errors; topology differences explained |
| `party` | map | `party/party_report.json`, `party/party_filmstrip.png` | 0 problems; every unreached node intended |
| `upload` | map | server | server validates with 0 errors |

## Warnings

`score` fails (exit 1) on a validation error **or on any warning that isn't
explained**. A warning is a decision: fix the map, or list it in `job.json`:

```json
"expected_warnings": [
 {"dead_end_at": [5.5, 27.5], "why": "the stairs down: its way on is the exit to 2A"},
 {"disconnected": "room.r24", "why": "24 is sealed; only D's teleport reaches it"},
 {"match": "some warning text", "why": "…"}
]
```

Generated corridor names change between builds, so dead ends are matched by
place (within 1.5 cells), not by name.

`score` adds one check the validator doesn't have: **overlapping spaces**
(two rooms or corridors covering the same floor by more than a quarter of a
cell), which draw two sets of walls there. It found neighbouring caves both
claiming a rock cell's floor on 1C. Most warnings on these maps turned out
to be real defects when first looked at (a cave's stray floor as a corridor, a
secret room that was a dead-end corridor, a statue alcove cut off its room);
the ones that remain are exits, which the validator doesn't count.

## Party-view check

`party.py` walks the map as a party: enter a space, see its non-secret doors
(exactly what a session reveal does), move through any passable door. After
every step it rebuilds the players' view with the functions a live session
uses and fails on any leak: undiscovered spaces or doors drawn, unfound
secret doors drawn, secret features (traps) visible, top-level features
(which ignore fog), GM text or unexplored room names in the room text or the
SVG. It also lists what can't be reached — expected for secret doors, locked
doors and sealed rooms, but each should be intended. `open` and
`reveal_secret` in `job.json` (door keys), or `open_all` / `reveal_all`,
simulate the GM unlocking doors and revealing found secret doors as the party
reaches them, so a second walk proves those areas open up properly. Exits are
checked too: a top-level exit ignores the fog, and a secret exit must stay
hidden.

Run it on any map, converted or hand-made:

```bash
uv run --with cairosvg --with pillow python tools/extract/party.py MAP.dmap --start 1
```

## Style kits

`styles/<name>/` holds what's true for every page drawn the same way:
`style.json` (rock grey, text darkness, label height, thresholds) and the
symbol templates (`door.png`, `S.png`, `arch.png`, `plain.png`), cut by
`make_templates.py` from a known page with the coordinates recorded there.
A new symbol: cut a clean instance, add it to `make_templates.py`, map it to
a door type in `style.json`'s `templates`.

## What it detects, and what it doesn't (yet)

Detected: grid, floor, caves vs straight walls, labels (positions), doors /
secret doors / archways on grid lines, doors / locked doors / portcullises
drawn mid-cell in a one-cell passage, drawn walls between floor cells, pillar
dots.

**Filled (locked) doors** on grid lines are found structurally, not by
template (their grey fill correlates with any plain line): a block 7-11 px
across with a dark fill, 12-23 px along the line, floor both sides, the line
thin past both ends, standing in a wall. Two short blocks with a white gap are
a locked double door; split by a crossing grid line, one door centred on a
lattice point. Thresholds are `filled_door` in `style.json` (defaults in
`symbols.py`).

**Off-grid shapes** (`vector.py`, before the grid pass; `"vector": false` in
`job.json` turns it off). The grid pass reads floor cell by cell, which turns
a round room into a staircase and a slanted passage into a zig-zag — and
reads both as cave walls. So they're found first, from the rock boundary:

- *Round rooms*: Hough circles kept only when the rim is wall (rock outside,
  floor inside) and hugs the circle to a pixel — an octagon's sides, or a
  square room's walls touched from inside, only graze it. Emitted as
  `circle at … radius …`, named by the label inside; its doors sit on the rim,
  and a door drawn there off the lattice is matched in the passage's frame.
- *Slanted passages*: straight rock edges off 0°/90°, paired with a parallel
  edge a passage-width away (floor between, rock outside), then traced both
  ways, re-centring between the walls each step (printed bands wobble and
  bend a few degrees). A trace stops at a round room's rim, at a dead end, off
  the page, or where the passage opens into a space — and carries on past a
  corridor it crosses as a second piece. Emitted as a one-segment corridor of
  the measured width, joined to the space at each end by the door drawn
  there (templates sampled across the passage, at its angle) or an opening.

Their cells leave the grid pass, and pillar dots on their seams (the wedge
of rock where a spoke meets a rim) are dropped. On Stonehell it finds
nothing on Level 1 and the surface, and 3D's seven round rooms and twelve
spokes, 3B's four, 3A's shaft room, and the 45° passages of 2A, 2C, 5A, 5D.

Not detected: diagonal walls *drawn* across white cells (2A's 22/12/13 —
lines, not rock edges), stippled or hatched floor.

Not yet — corrections:

- Icons (statues, stairs, traps, pools, stalls) — placed by the reader at
  cell precision, as `features` corrections.
- Door symbols outside the kit (double doors, gates, one-way arrows, bashed-in
  doors, concealed "C").
- `line_feature`s (bars, fences) — not emitted.
- Non-grid maps, hex maps, hand-drawn maps without a grid.

`boxes.json`, `symbols.json` and `dots.json` are written sorted by position;
`labels.json` follows `boxes.json` by position — re-running `prep` after a
threshold change remaps it and marks new boxes `"?"`, so nothing shifts
silently.

Per-module records of what each map needed live next to the job folders —
for Stonehell, `modules/stonehell/conversion/LIMITATIONS.md`.
