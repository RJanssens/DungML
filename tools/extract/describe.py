"""Step 3 — pull the room key out of the module text, split into what the party
perceives (`description`) and what only the GM knows (`dm_notes`).

The module is read as markdown text. `key.json` in the job folder says where:

  text       path to the module text
  sheet      the exact line that starts this map's key sheet
  key        [start, end] markers around the numbered room key ("N. Title: text")
  features_key, legend, wandering   [start, end] markers, optional
  overview   {"heading": first line of the overview, "map_description":
              [paragraph prefixes]} — optional, becomes the map's description
  desc_sentences  {"room": [[sentence indices], "why"]} — rooms where the rule
                  below gets the split wrong
  extras     text folded into a room's dm_notes, each one of:
               {"room", "title", "list": [start, end], "max"?}  a numbered list
               {"room", "title", "columns": [start, end], "headers": [..]}
                    a table printed as interleaved numbered columns
               {"room", "paragraph": prefix, "prefix"?, "first_sentence"?, "suffix"?}
                    an overview paragraph (NPCs, special notes, new spells)

The split rule: one-page keys give what the party perceives first (sights,
smells, furnishings) and the GM material after (monsters, treasure, traps,
mechanics). Sentences before the first GM-looking sentence are description;
that sentence and the rest are dm_notes. It's right for most entries and
wrong for a few, which `desc_sentences` fixes with a reason — review them.

Writes descriptions.json to the job folder.
"""
from __future__ import annotations

import re
from pathlib import Path

from common import Job, load_json, save_json

GM = re.compile(r"""\(\d|\d+d\d|\bsave vs|\btrap|\bchance\b|\b\d[\d,]*\s*(gp|sp|cp)\b|\bgp\b|\bsp\b|\bcp\b|
                    \bsee\b|\bIf\b|\bif\b|\blives here|\battack|\balert|\bsummon|\bunaware|\bstash|\bRoll\b|
                    \banswers\b|\bUnder a\b|\bstore\b|\bSecret\b|\bpotion|\bteleport|\bactivates|\breturn after|
                    \bEmpty\.|\bHD\b|\bspell|\bwill\b|\bterrified|\ben route|\bon watch|\blive in|\bDwarves \(|
                    \btaking notes|\bSounds of work from""", re.X)


def sentences(t: str) -> list[str]:
    t = t.replace("&", "and")
    return [p.strip() for p in re.split(r'(?<=[.!?"])\s+(?=[A-Z0-9"])', t) if p.strip()]


def main(job: Job) -> None:
    cfg = load_json(job.dir / "key.json")
    lines = Path(cfg["text"]).expanduser().read_text().split("\n")
    start = next(n for n, l in enumerate(lines) if l.strip() == cfg["sheet"])

    def at(marker: str, frm: int) -> int:
        return next(n for n in range(frm, len(lines)) if lines[n].strip().startswith(marker))

    def section(bounds, frm=start, with_marker=False) -> list[str]:
        a = at(bounds[0], frm)
        b = at(bounds[1], a + 1)
        return [l for l in lines[a + (0 if with_marker else 1):b] if l.strip()]

    # the numbered room key; continuation lines join the entry above
    entries: dict[str, str] = {}
    cur = None
    for l in section(cfg["key"]):
        m = re.match(r"^(\d+)\. (.*)$", l)
        if m and (cur is None or int(m.group(1)) == int(cur) + 1):
            cur = m.group(1)
            entries[cur] = m.group(2)
        elif cur:
            entries[cur] += " " + l.strip()

    over = cfg.get("desc_sentences", {})
    rooms = {}
    for n, text in entries.items():
        title, _, body = text.partition(": ")
        ss = sentences(body)
        cut = next((k for k, s in enumerate(ss) if GM.search(s)), len(ss))
        keep = over[n][0] if n in over else list(range(cut))
        rooms[n] = {"title": title.strip(),
                    "description": " ".join(s for k, s in enumerate(ss) if k in keep),
                    "dm_notes": " ".join(s for k, s in enumerate(ss) if k not in keep)}

    ov = cfg.get("overview", {})
    ov_start = next((n for n, l in enumerate(lines) if l.startswith(ov["heading"])), None) if ov else None
    ov_text = "\n".join(lines[ov_start:ov_start + 60]) if ov_start is not None else ""

    def para(prefix: str) -> str:
        m = re.search(re.escape(prefix) + r".*?(?=\n\n|\Z)", ov_text, re.S)
        return re.sub(r"\s+", " ", m.group(0)).strip() if m else ""

    def numbered(ls):
        return [l.strip() for l in ls if re.match(r"^\d+\.", l.strip())]

    for x in cfg.get("extras", []):
        r = rooms[x["room"]]
        if "list" in x:
            items = numbered(section(x["list"]))[: x.get("max")]
            r["dm_notes"] += f"\n\n{x['title']}:\n" + "\n".join(items)
        elif "columns" in x:
            items = numbered(section(x["columns"]))
            cols = [items[k::len(x["headers"])] for k in range(len(x["headers"]))]
            parts = [f"{h} " + "; ".join(i.split(". ", 1)[1] for i in col) for h, col in zip(x["headers"], cols)]
            r["dm_notes"] += f"\n\n{x['title']}: " + " / ".join(parts) + "."
        elif "paragraph" in x:
            p = para(x["paragraph"])
            if x.get("first_sentence"):
                p = p.split(". ")[0] + "."
            r["dm_notes"] = (r["dm_notes"] + " " + x.get("prefix", "") + p + x.get("suffix", "")).strip()

    feats = {}
    if "features_key" in cfg:
        last = None
        for l in section(cfg["features_key"]):
            m = re.match(r"^([A-Z]): (.*)$", l.strip())
            if m:
                last = m.group(1)
                feats[last] = m.group(2)
            elif last:
                feats[last] += " " + l.strip()

    traps = {}
    if "legend" in cfg:
        legend = " ".join(l.strip() for l in section(cfg["legend"]))
        for item in legend.split("–")[1:]:
            name, _, rest = item.strip().partition(" (")
            traps[name.replace(" Trap", "").strip()] = rest.strip().rstrip(")").strip()

    map_notes = ""
    if "wandering" in cfg:
        wm = section(cfg["wandering"], with_marker=True)   # its heading wraps onto a second line
        head = " ".join(l.strip() for l in wm if not re.match(r"^\d+\.", l.strip()))
        rolls = [l.strip().split(". ", 1)[1] for l in wm if re.match(r"^\d+\.", l.strip())]
        ranges: list[list] = []
        for k, m in enumerate(rolls, 1):
            if ranges and ranges[-1][2] == m:
                ranges[-1][1] = k
            else:
                ranges.append([k, k, m])
        check = re.sub(r"\*\*|Wandering Monsters", "", head).strip(" ()")
        map_notes = (f"Wandering monsters ({check}). Roll d{len(rolls)}: "
                     + "; ".join((f"{a}" if a == b else f"{a}-{b}") + f" {m}" for a, b, m in ranges) + ".")
    map_desc = " ".join(p for p in (para(x) for x in ov.get("map_description", [])) if p)

    save_json(job.dir / "descriptions.json", {
        "rooms": rooms, "features_key": feats, "traps": traps,
        "map": {"description": map_desc, "dm_notes": map_notes},
        "split_overrides": {k: v[1] for k, v in over.items()},
    })
    print(f"describe: {len(rooms)} rooms, features {sorted(feats)}, traps {sorted(traps)}, "
          f"{len(over)} split overrides")
