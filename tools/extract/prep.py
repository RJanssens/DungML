"""Step 1 — read the page: grid, rock, floor per cell, and where the labels are.

Writes to work/:
  grid.json        cells per side and pitch in px (detected unless job.json fixes it)
  rock.npy         pixel mask of solid rock (the style's rock grey, 5x5-opened so
                   anti-aliased text edges don't count)
  frac.npy         per cell, the share of its interior that is not rock
  notext.png       the page with dark text blanked (symbol matching reads this)
  boxes.json       label boxes: dark glyph clusters of label height
  labels_sheet.png every box, numbered, for a person or a model to read

The labels themselves are *not* read here: code finds where they are, a
reader says what they say, in `labels.json` (one string per box, in order;
"" or "-" for a box that isn't a label). A `labels.todo.json` with the boxes is
written when `labels.json` doesn't exist yet.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as nd

from common import Job, save_json


def detect_pitch(g: np.ndarray, style: dict) -> float:
    """Cell pitch from the periodicity of the grid lines (mid-grey pixels)."""
    lo, hi = style["gridline_grey"]
    mid = (g > lo) & (g < hi)
    w = g.shape[1]
    best = None
    for axis in (0, 1):
        prof = mid.sum(axis).astype(float)
        spec = np.abs(np.fft.rfft(prof - prof.mean()))
        # FFT index = periods across the page = cells; plausible grids are 12..60
        k0, k1 = 12, 60
        k = k0 + int(np.argmax(spec[k0:k1 + 1]))
        if best is None or spec[k] > best[1]:
            best = (k, spec[k])
    return w / best[0]


def main(job: Job) -> None:
    g = job.gray()
    st = job.style
    fixed = job.cfg.get("grid", {})
    pitch = fixed.get("pitch") or (g.shape[1] / fixed["cells"] if "cells" in fixed else detect_pitch(g, st))
    n = int(round(g.shape[1] / pitch))
    save_json(job.work / "grid.json", {"cells": n, "pitch": pitch})

    lo, hi = st["rock_grey"]
    rock = nd.binary_dilation(nd.binary_erosion((g > lo) & (g < hi), np.ones((5, 5))), np.ones((5, 5)))
    np.save(job.work / "rock.npy", rock)

    frac = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            y0, y1 = int(round(i * pitch)) + 3, int(round((i + 1) * pitch)) - 3
            x0, x1 = int(round(j * pitch)) + 3, int(round((j + 1) * pitch)) - 3
            frac[i, j] = 1 - rock[y0:y1, x0:x1].mean()
    np.save(job.work / "frac.npy", frac)

    dark = g < st["text_dark"]
    Image.fromarray(np.where(nd.binary_dilation(dark, np.ones((5, 5))), 255, g).astype("uint8")) \
        .save(job.work / "notext.png")

    # label boxes: dark connected components, merged into words
    lab, _ = nd.label(dark, np.ones((3, 3)))
    comps = []
    for k, s in enumerate(nd.find_objects(lab)):
        if s is not None and (lab[s] == k + 1).sum() >= 6:
            comps.append([s[1].start, s[0].start, s[1].stop, s[0].stop])
    comps.sort()
    words: list[list[int]] = []
    for x0, y0, x1, y1 in comps:
        for w in words:
            if x0 <= w[2] + 6 and x1 >= w[0] - 6 and y0 <= w[3] + 3 and y1 >= w[1] - 3:
                w[:] = [min(w[0], x0), min(w[1], y0), max(w[2], x1), max(w[3], y1)]
                break
        else:
            words.append([x0, y0, x1, y1])
    hmin, hmax = st["label_height"]
    boxes = [w for w in words if hmin <= w[3] - w[1] <= hmax]
    save_json(job.work / "boxes.json", boxes)

    im = Image.open(job.image).convert("L")
    per = 8
    sheet = Image.new("L", (per * 90, ((len(boxes) + per - 1) // per) * 56), 255)
    d = ImageDraw.Draw(sheet)
    for k, (x0, y0, x1, y1) in enumerate(boxes):
        c = im.crop((x0 - 4, y0 - 4, x1 + 4, y1 + 4))
        c = c.resize((c.width * 2, c.height * 2))
        X, Y = (k % per) * 90, (k // per) * 56
        sheet.paste(c, (X + 22, Y + 4))
        d.text((X + 1, Y + 2), str(k), fill=0)
    sheet.save(job.work / "labels_sheet.png")

    if not (job.dir / "labels.json").exists():
        save_json(job.dir / "labels.todo.json",
                  {"read": "labels_sheet.png — write labels.json: a list of the text of each "
                           "box, in order; \"-\" for a box that is not a label",
                   "boxes": boxes})
    print(f"prep: {n}x{n} cells at {pitch:.2f}px, {int((frac > 0.3).sum())} floor cells, "
          f"{len(boxes)} label boxes -> {job.work / 'labels_sheet.png'}")
