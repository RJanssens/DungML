"""Step 2 — find door-like symbols on the grid lines by template matching.

Every lattice line between two floor cells is scanned, 1 px at a time and ±1 px
across (printed lines drift a pixel), against the style's templates. A
template's score is how much better it fits than a plain grid line does
(`ncc(window, template) - ncc(window, plain)`), so a faint symbol over a strong
line still stands out. Hits above the style's margin survive non-maximum
suppression along each line; a `door` hit must also be hollow (white where the
line would run), which rejects drawn walls.

Writes work/symbols.json and work/symbols_dbg.png (hits circled on the page:
red door, blue secret, green arch). What the templates don't know — a
portcullis drawn mid-cell, a filled double door, a one-way arrow — is added in
`corrections.json` and counted as a correction.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from common import Job, Style, save_json


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d else 0.0


def main(job: Job) -> None:
    st = job.style
    style = Style(job.cfg.get("style", "stonehell"))
    n, pitch = job.grid()
    g = np.asarray(Image.open(job.work / "notext.png"), float)
    frac = np.load(job.work / "frac.npy")
    floor = frac > st["floor_min_frac"]
    A, L = st["template_half"]["across"], st["template_half"]["along"]
    temps = {name: style.template(name) for name in st["templates"]}
    plain = style.template("plain")
    # a plain grid crossing: what a lattice-point-centred window looks like with no symbol
    plains = [plain] + ([style.template("plain_x")] if (style.dir / "plain_x.png").exists() else [])

    hits = []
    for orient, img, fl in (("v", g, floor), ("h", g.T, floor.T)):
        # a letter (S) is printed upright on any line, so it has a template per orientation;
        # mid_only symbols (1C's filled locked door, the portcullis dots) never sit on a grid line
        here = {nm: tm for nm, tm in temps.items() if st["templates"][nm].get("orient", orient) == orient
                and not st["templates"][nm].get("mid_only")}
        for k in range(1, n):
            x = int(round(k * pitch))
            for yy in range(L, img.shape[0] - L):
                c = int(yy // pitch)
                if c >= n or not (fl[c, k - 1] and fl[c, k]):
                    continue
                best = (0.0, None)
                for dx in (-1, 0, 1):
                    w = img[yy - L:yy + L + 1, x + dx - A:x + dx + A + 1]
                    if w.shape != plain.shape:
                        continue
                    base = max(ncc(w, plain), 0.0)
                    base_x = max(max(ncc(w, p) for p in plains), 0.0)
                    for name, tm in here.items():
                        # only a symbol that is itself centred on a lattice point has to beat a
                        # plain crossing; a door can sit on one too (32's) and must not be penalised
                        s = ncc(w, tm) - (base_x if st["templates"][name].get("width", 1) > 1 else base)
                        if s > best[0]:
                            best = (s, name)
                if best[0] > st["template_margin"]:
                    hits.append(dict(o=orient, k=k, p=yy, s=round(best[0], 3), t=best[1]))

    # mid-cell symbols: a door or portcullis drawn across the middle of a one-cell
    # passage (floor on both ends, rock on both sides). There is no grid line down
    # the middle of a cell, so the template score stands on its own.
    for orient, img, fl in (("v", g, floor), ("h", g.T, floor.T)):
        here = {nm: tm for nm, tm in temps.items() if st["templates"][nm].get("orient", orient) == orient
                and st["templates"][nm].get("width", 1) == 1}
        for r in range(1, n - 1):
            for c in range(1, n - 1):
                if not (fl[r, c - 1] and fl[r, c] and fl[r, c + 1] and not fl[r - 1, c] and not fl[r + 1, c]):
                    continue
                x = int(round((c + .5) * pitch))
                best = (0.0, None, 0)
                for yy in range(int(r * pitch) + 4, int((r + 1) * pitch) - 4):
                    for dx in (-2, -1, 0, 1, 2):
                        w = img[yy - L:yy + L + 1, x + dx - A:x + dx + A + 1]
                        # an empty passage cell is near-uniform white: its correlation with
                        # anything is noise, so a mid-cell window must actually hold ink
                        if w.shape != plain.shape or w.std() < st.get("mid_cell_min_std", 20):
                            continue
                        for name, tm in here.items():
                            s = ncc(w, tm)
                            if s > best[0]:
                                best = (s, name, yy)
                if best[0] > st.get("mid_cell_margin", 1):
                    # (r, c) is in the scan image's frame; `cell` is stored in page (row, col)
                    hits.append(dict(o=orient, k=c + .5, p=best[2], s=round(best[0], 3), t=best[1], mid=True,
                                     cell=[r, c] if orient == "v" else [c, r]))

    # filled (locked) doors on a grid line: a grey block 7-11 px across (fill ~135)
    # and 12-23 px along the line, floor on both sides (measured on pages 82, 92,
    # 99; a hollow door is white inside, a drawn wall or a ruin's dash is 5 px of a
    # paler grey, 163-192, a grid line 1-3 px); a locked double door is two short
    # blocks with a gap. No template: the grey fill correlates
    # with every stretch of plain line. The line is scanned whole, since a door
    # centred on a lattice point spans two cells.
    fd = st.get("filled_door", {"width": [7, 11], "length": [12, 23], "leaf": [7, 13], "fill": [120, 200],
                                "inner_max": 175, "white": 205})
    for orient, img, fl in (("v", g, floor), ("h", g.T, floor.T)):
        H = img.shape[0]
        for k in range(1, n):
            x = int(round(k * pitch))
            strip = img[:, x - 9:x + 10]
            dark = (strip < fd["fill"][1]).sum(1)                  # dark width per row
            inner = strip[:, 7:12].mean(1)
            side = np.minimum(strip[:, :2].min(1), strip[:, -2:].min(1))
            cell = np.minimum((np.arange(H) / pitch).astype(int), n - 1)
            between = fl[cell, k - 1] & fl[cell, k]
            row_ok = between & (dark >= fd["width"][0]) & (dark <= fd["width"][1]) & (inner >= fd["fill"][0]) \
                & (inner < fd["inner_max"]) & (side >= fd["white"])
            runs, i = [], 0
            while i < H:
                if row_ok[i]:
                    j = i
                    while j + 1 < H and row_ok[j + 1]:
                        j += 1
                    runs.append((i, j + 1))
                    i = j + 1
                else:
                    i += 1

            def thin_past(a0, a1):
                # a door is a block *in* a line: past both ends the line runs on thin.
                # A stretch of thick grey wall between a door and a corner (1B's crypt
                # walls) runs into rock at one end. (A crossing grid line is one dark row.)
                before, after = dark[max(a0 - 6, 0):max(a0 - 2, 0)], dark[a1 + 2:a1 + 6]
                return bool(len(before) and len(after) and np.median(before) <= 4 and np.median(after) <= 4)

            def gap_kind(g0, g1):
                # between two blocks: a white gap is a double door's two leaves (inner
                # >200 on 3B, 3D); a full-width dark row is a crossing grid line, and
                # the blocks are one door centred on a lattice point (2A's 15,13, 3C's
                # 7,17); anything else is a rock edge crossing the line (0A's cave 15)
                if g1 <= g0:
                    return None
                if dark[g0:g1].max() >= 15:
                    return "crossing"
                if inner[g0:g1].max() >= 190:
                    return "leaves"
                return None

            def in_wall(a0, a1):
                # a door stands in a wall or a passage's mouth: along the line, next to
                # it, is rock on one side or a drawn wall (darker than a grid line). A
                # grey block on open floor (2D 38's crusher icon) has grid line both ways
                for yy in (a0 - int(pitch * 0.6), a1 + int(pitch * 0.6)):
                    if not 0 <= yy < H:
                        return True
                    cc = min(int(yy / pitch), n - 1)
                    if not (fl[cc, k - 1] and fl[cc, k]):
                        return True
                    seg = strip[max(yy - 4, 0):yy + 5, 6:13]
                    if np.median(seg.min(1)) < 150:
                        return True
                return False

            used = set()
            for r, (a0, a1) in enumerate(runs):
                if r in used:
                    continue
                L = a1 - a0
                nxt = runs[r + 1] if r + 1 < len(runs) else None
                if nxt and fd["leaf"][0] <= L <= fd["leaf"][1] and fd["leaf"][0] <= nxt[1] - nxt[0] <= fd["leaf"][1] \
                        and nxt[0] - a1 <= 6 and in_wall(a0, nxt[1]) and gap_kind(a1, nxt[0]):
                    # (two leaves fill the opening corner to corner: no thin line past them)
                    used.add(r + 1)
                    p = (a0 + nxt[1]) // 2
                    single = gap_kind(a1, nxt[0]) == "crossing"
                    if not any(h["t"] in ("filled", "filled2") and h["o"] == orient and h["k"] == k
                               and abs(h["p"] - p) < pitch for h in hits):   # three leaf-like runs: one door
                        hits.append(dict(o=orient, k=k, p=p, s=1.0, t="filled" if single else "filled2"))
                elif fd["length"][0] <= L <= fd["length"][1] and thin_past(a0, a1) and in_wall(a0, a1):
                    hits.append(dict(o=orient, k=k, p=(a0 + a1) // 2, s=1.0, t="filled"))

    def hollow(h) -> bool:
        if h.get("mid"):
            return True
        img = g if h["o"] == "v" else g.T
        x = int(round(h["k"] * pitch))
        return img[h["p"] - 3:h["p"] + 4, x - 1:x + 2].mean(1).min() > st["door_hollow_min"]

    hits = [h for h in hits if h["t"] != "door" or h["s"] >= st.get("door_sure", 1) or hollow(h)]
    hits.sort(key=lambda h: -h["s"])
    keep: list[dict] = []
    for h in hits:
        if all(not (h["o"] == q["o"] and h["k"] == q["k"] and abs(h["p"] - q["p"]) < st["nms_px"]) for q in keep):
            keep.append(h)
    for h in keep:
        if h["t"] in ("filled", "filled2"):
            h["type"], h["state"] = ("wooden" if h["t"] == "filled" else "double"), "locked"
            continue
        h["type"] = st["templates"][h["t"]]["type"]
        if w := st["templates"][h["t"]].get("width"):
            h["width"] = w
        if s := st["templates"][h["t"]].get("state"):
            h["state"] = s
    keep.sort(key=lambda h: (h["o"], h["k"], h["p"]))   # by position, not by score, before persisting
    save_json(job.work / "symbols.json", keep)

    im = Image.open(job.image).convert("RGB")
    d = ImageDraw.Draw(im)
    col = {"wooden": (220, 0, 0), "secret": (0, 0, 255), "arch": (0, 170, 0)}
    for h in keep:
        x, y = (round(h["k"] * pitch), h["p"]) if h["o"] == "v" else (h["p"], round(h["k"] * pitch))
        d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=col.get(h["type"], (255, 140, 0)), width=3)
    im.save(job.work / "symbols_dbg.png")
    dots = find_dots(job, pitch, n)
    # a portcullis is three dots; its dots are not pillars
    bars = [((h["k"], h["p"] / pitch) if h["o"] == "v" else (h["p"] / pitch, h["k"])) for h in keep
            if h["type"] == "portcullis"]
    dots = [p for p in dots if all(abs(p[0] - bx) + abs(p[1] - by) > 0.8 for bx, by in bars)]
    dots.sort(key=lambda p: (p[1], p[0]))
    save_json(job.work / "dots.json", dots)
    for x, y in dots:
        d.ellipse([x * pitch - 5, y * pitch - 5, x * pitch + 5, y * pitch + 5], outline=(160, 0, 200), width=2)
    im.save(job.work / "symbols_dbg.png")
    counts = {t: sum(h["type"] == t for h in keep) for t in sorted({h["type"] for h in keep})}
    print(f"symbols: {len(keep)} hits {counts}, {len(dots)} pillar dots -> {job.work / 'symbols_dbg.png'}")


def find_dots(job: Job, pitch: float, n: int) -> list[list[float]]:
    """Pillars: small round blobs of rock-grey ink standing alone on floor,
    as map coordinates snapped to half cells. Three dots in a row inside one
    cell are something else (1A's portcullis at B), so a dot with a neighbour
    closer than half a cell is skipped."""
    from scipy import ndimage as nd
    rock = np.load(job.work / "rock.npy")
    lab, k = nd.label(rock)
    found = []
    for idx, s in enumerate(nd.find_objects(lab), 1):
        if s is None:
            continue
        h, w = s[0].stop - s[0].start, s[1].stop - s[1].start
        area = int((lab[s] == idx).sum())
        # round: about as wide as tall, filling most of its box; small against a cell
        if not (5 <= h <= pitch * 0.5 and 5 <= w <= pitch * 0.5 and abs(h - w) <= 3 and area >= 0.6 * h * w):
            continue
        if min(s[0].start, s[1].start) < 4 or s[0].stop > rock.shape[0] - 4 or s[1].stop > rock.shape[1] - 4:
            continue                                # a nick in the page border, not a pillar
        ring = lab[s[0].start - 3:s[0].stop + 3, s[1].start - 3:s[1].stop + 3]
        if np.isin(ring, [0, idx]).all():          # surrounded by floor, not a rock edge
            cy, cx = (s[0].start + s[0].stop) / 2, (s[1].start + s[1].stop) / 2
            found.append((cx / pitch, cy / pitch))
    alone = [p for p in found if all(q is p or abs(q[0] - p[0]) + abs(q[1] - p[1]) >= 0.5 for q in found)]
    return [[round(x * 2) / 2, round(y * 2) / 2] for x, y in alone]
