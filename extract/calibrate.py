#!/usr/bin/env python3
"""Probe the true grid pitch + origin and dump an overlay image to eyeball it."""
import sys
import numpy as np
from PIL import Image, ImageDraw

path = sys.argv[1]
im = Image.open(path).convert("L")
gray = np.asarray(im, dtype=np.float64)
h, w = gray.shape

# Floor mask: light pixels.
mask = (gray > 150).astype(np.float64)

# Column/row profiles: where are the wall lines (low light density)?
col = mask.mean(axis=0)
row = mask.mean(axis=1)


def autocorr_pitch(sig, lo=12, hi=45):
    sig = sig - sig.mean()
    best, bestv = lo, -1e9
    for lag in range(lo, hi):
        v = np.dot(sig[:-lag], sig[lag:])
        if v > bestv:
            bestv, best = v, lag
    return best


px = autocorr_pitch(col)
py = autocorr_pitch(row)
print(f"# pitch col={px} row={py}", file=sys.stderr)

# Find origin: first x where wall structure begins. Use the dark frame: the
# content starts after the leftmost sustained light region. Simpler: scan
# offsets, score how well cell centers land on extreme (very light/dark) pixels.
pitch = (px + py) / 2.0


def score(ox, oy, pitch):
    ncx = int((w - ox) // pitch)
    ncy = int((h - oy) // pitch)
    vals = []
    for j in range(ncy):
        for i in range(ncx):
            cy = int(oy + (j + 0.5) * pitch)
            cx = int(ox + (i + 0.5) * pitch)
            vals.append(gray[cy, cx])
    vals = np.array(vals)
    return np.mean((vals > 200) | (vals < 110))


best = (0, 0, -1)
for oy in range(0, int(pitch)):
    for ox in range(0, int(pitch)):
        s = score(ox, oy, pitch)
        if s > best[2]:
            best = (ox, oy, s)
ox, oy, s = best
ncx = int((w - ox) // pitch)
ncy = int((h - oy) // pitch)
print(f"# origin=({ox},{oy}) pitch={pitch:.2f} grid={ncx}x{ncy} crisp={s:.3f}", file=sys.stderr)

# Overlay
rgb = Image.open(path).convert("RGB")
d = ImageDraw.Draw(rgb)
for i in range(ncx + 1):
    x = ox + i * pitch
    d.line([(x, oy), (x, oy + ncy * pitch)], fill=(255, 0, 0), width=1)
for j in range(ncy + 1):
    y = oy + j * pitch
    d.line([(ox, y), (ox + ncx * pitch, y)], fill=(255, 0, 0), width=1)
rgb.save("extract/overlay.png")
print("# wrote extract/overlay.png", file=sys.stderr)
