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

    hits = []
    for orient, img, fl in (("v", g, floor), ("h", g.T, floor.T)):
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
                    for name, tm in temps.items():
                        s = ncc(w, tm) - base
                        if s > best[0]:
                            best = (s, name)
                if best[0] > st["template_margin"]:
                    hits.append(dict(o=orient, k=k, p=yy, s=round(best[0], 3), t=best[1]))

    def hollow(h) -> bool:
        img = g if h["o"] == "v" else g.T
        x = int(round(h["k"] * pitch))
        return img[h["p"] - 3:h["p"] + 4, x - 1:x + 2].mean(1).min() > st["door_hollow_min"]

    hits = [h for h in hits if h["t"] != "door" or hollow(h)]
    hits.sort(key=lambda h: -h["s"])
    keep: list[dict] = []
    for h in hits:
        if all(not (h["o"] == q["o"] and h["k"] == q["k"] and abs(h["p"] - q["p"]) < st["nms_px"]) for q in keep):
            keep.append(h)
    for h in keep:
        h["type"] = st["templates"][h["t"]]["type"]
    save_json(job.work / "symbols.json", keep)

    im = Image.open(job.image).convert("RGB")
    d = ImageDraw.Draw(im)
    col = {"wooden": (220, 0, 0), "secret": (0, 0, 255), "arch": (0, 170, 0)}
    for h in keep:
        x, y = (round(h["k"] * pitch), h["p"]) if h["o"] == "v" else (h["p"], round(h["k"] * pitch))
        d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=col.get(h["type"], (255, 140, 0)), width=3)
    im.save(job.work / "symbols_dbg.png")
    counts = {t: sum(h["type"] == t for h in keep) for t in sorted({h["type"] for h in keep})}
    print(f"symbols: {len(keep)} hits {counts} -> {job.work / 'symbols_dbg.png'}")
