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
`["core.dmap"]`. `door_text` names features-key entries that describe a door
type (Stonehell's "A: Archways…", "B: Lowered portcullis…"). `reference` is an
existing hand-made map to compare topology with. `party` configures the walk
(see *Party-view check*).

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
| `label_cell` | `{"12": [i, j]}` | a label printed outside its room |
| `not_floor` | `[[i, j]]` | white art that isn't floor |
| `features` | `[{type, at, scale?, description?, dm_notes?}]` | icons, at cell precision; `description`/`dm_notes` may be literal text or a reference `"features_key.C"` / `"traps.Pit"` into `descriptions.json` |

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

## Party-view check

`party.py` walks the map as a party: enter a space, see its non-secret doors
(exactly what a session reveal does), move through any passable door. After
every step it rebuilds the players' view with the functions a live session
uses and fails on any leak: undiscovered spaces or doors drawn, unfound
secret doors drawn, secret features (traps) visible, top-level features
(which ignore fog), GM text or unexplored room names in the room text or the
SVG. It also lists what can't be reached — expected for secret doors, locked
doors and sealed rooms, but each should be intended. `open` and
`reveal_secret` in `job.json` simulate the GM unlocking doors and revealing
found secret doors, so a second walk proves those areas open up properly.

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

## What it doesn't do (yet)

- Symbols off the grid lines (a portcullis drawn mid-cell), filled/double
  doors, one-way arrows, drawn walls between floor cells — corrections.
- Icons (statues, stairs, traps, pools) — placed by the reader at cell
  precision, as `features` corrections.
- Exits to other maps (`exit … to "map" at x,y`) — need the target map.
- Non-grid maps, hex maps, hand-drawn maps without a grid.

Per-module records of what each map needed live next to the job folders —
for Stonehell, `modules/stonehell/conversion/LIMITATIONS.md`.
