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
        # a letter (S) is printed upright on any line, so it has a template per orientation
        here = {nm: tm for nm, tm in temps.items() if st["templates"][nm].get("orient", orient) == orient}
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

    def hollow(h) -> bool:
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
        h["type"] = st["templates"][h["t"]]["type"]
        if w := st["templates"][h["t"]].get("width"):
            h["width"] = w
    save_json(job.work / "symbols.json", keep)

    im = Image.open(job.image).convert("RGB")
    d = ImageDraw.Draw(im)
    col = {"wooden": (220, 0, 0), "secret": (0, 0, 255), "arch": (0, 170, 0)}
    for h in keep:
        x, y = (round(h["k"] * pitch), h["p"]) if h["o"] == "v" else (h["p"], round(h["k"] * pitch))
        d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=col.get(h["type"], (255, 140, 0)), width=3)
    im.save(job.work / "symbols_dbg.png")
    dots = find_dots(job, pitch, n)
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
