---
description: Convert a gridded dungeon-map page (+ its module key) into a DungML map, verified with a party-view walk
argument-hint: <job folder> | <page image> <module text> <name>
---

Convert a map page to DungML with the pipeline in `tools/extract/`. Read
`tools/extract/README.md` first — it defines the job folder, every
correction type and what each step checks. Arguments: $ARGUMENTS

Work from the repo root. Every step is:

```bash
uv run --with pillow --with numpy --with scipy --with scikit-image --with cairosvg \
    python tools/extract/convert.py STEP JOB
```

## 1. Set up the job

If given a job folder that has `job.json`, use it. Otherwise create one next
to the module's other conversions (for Stonehell:
`~/roleplaying/modules/stonehell/conversion/<name>/`) with a `job.json`
(name, title, image, style, and `reference` if a hand-made map of this page
exists). Copy the shape from an existing job, e.g. `conversion/1A/job.json`.

## 2. prep → read the labels

Run `prep`. Open `work/labels_sheet.png` and write `labels.json`: one string
per numbered box, in order, exactly as printed (`"12"`, `"B"`, `"Cpt"`); `"-"`
for a box that isn't a label (a black icon, a pit). You read the text —
never positions; code already has those.

## 3. symbols → check the doors

Run `symbols`. Compare `work/symbols_dbg.png` with the page: every door,
secret door and archway circled, nothing else. For anything the templates
don't know — a portcullis, double/locked door, one-way arrow, drawn wall,
bars, symbols unique to this page — add a `corrections.json` entry with a
`_why` line. Take positions from the grid (cell `[row, col]`, edge
coordinates `x.5`), never from pixel guesses. If a symbol recurs across
pages, add it to the style kit instead (README, *Style kits*).

## 4. describe → the key

Write `key.json`: find this map's key sheet in the module text (its exact
first line), the markers around the room key, features key, legend and
wandering table, and the overview paragraphs for the map description. Run
`describe`, then **read every room's split** in `descriptions.json`: the
description must be only what a party perceives on entering; monsters,
treasure, traps, mechanics, destinations and cross-references go to
dm_notes. Fix wrong splits with `desc_sentences` (+ reason). Fold tables and
NPC/spell notes a room depends on into it with `extras`.

## 5. features

From the page's icons and the legend/key, add `features` corrections: type
(an existing library `feature_def` — check `packages/dsl/src/dungml/includes/`),
position at cell precision, and text by reference (`"features_key.C"`,
`"traps.Pit"`) or quoted from the key. The builder nests each feature in its
room/corridor so fog hides it. **If no library feature fits, don't fake one
with a lookalike: note it in the module's `LIMITATIONS.md`** and either add a
feature_def to the right library (monochrome glyph for core; say which) or
leave the icon out.

## 6. build → score → party

Run `all` (or the steps singly). Then:

- `build`: "labels without a room" must be empty.
- `score`: IoU should be ≳ 0.9 and 0 errors. Look at `work/diff.png` — red is
  page floor the map misses, blue is map floor over rock. Explain every
  topology difference against the reference by looking at the page; the
  reference may be the one that's wrong (a missing corridor link, a door
  kept only as a feature) — record those.
- `party`: must report 0 problems. Look at `work/party/party_filmstrip.png`:
  the reveal should grow a corridor stretch or a room at a time. Every
  unreached node must be intended (secret, locked, sealed per the key); set
  `party.open` / `party.reveal_secret` in `job.json` and re-run to prove those
  areas open up.

Iterate on corrections until all three hold. Never hand-edit the `.dmap`:
everything goes through the job files so the map can be rebuilt.

## 7. Upload and record

Run `upload` (needs `upload` in `job.json`; `DUNGML_TOKEN` defaults to the
dev token). Then append this map's entry to the module's `LIMITATIONS.md`:
counts (rooms, corridors, doors by type, features, corrections by kind),
scores, what the DSL or libraries couldn't express, missing features, what
the templates missed, and reference-map errors found.
