#!/usr/bin/env python3
"""Recover a boolean floor/rock occupancy grid from a grid-aligned dungeon JPG.

The source maps (e.g. ../modules/.../73.jpg) are drawn on a square grid:
white-ish cells are open floor, grey cells are solid rock. We:

  1. Calibrate the grid pitch + origin offset from the image dimensions and
     a light-pixel projection (rooms snap to cell boundaries, so the floor
     mask has strong periodicity).
  2. Sample each cell's interior, threshold light-vs-grey -> floor[y][x].
  3. Emit an ASCII map with coordinate rulers so the geometry can be read
     off directly in dungml world coordinates.

Usage:
    python grid_extract.py IMAGE [--cols N] [--inset F] [--thresh T]
"""
import argparse
import sys

import numpy as np
from PIL import Image


def load_gray(path):
    im = Image.open(path).convert("L")
    return np.asarray(im, dtype=np.float64), im.size


def guess_pitch(w, h, cols):
    """Cell pitch in px. The maps are square-celled; trust the column count."""
    return w / cols


def calibrate_origin(gray, pitch, thresh):
    """Find the sub-cell offset that best aligns cell centers to floor blobs.

    Try a handful of offsets in [0, pitch) on each axis; pick the one whose
    sampled grid yields the crispest light/dark split (max variance of the
    per-cell mean -> cleanest bimodal separation)."""
    h, w = gray.shape
    best = (0.0, 0.0, -1.0)
    steps = np.linspace(0, pitch, 8, endpoint=False)
    for oy in steps:
        for ox in steps:
            ncx = int((w - ox) // pitch)
            ncy = int((h - oy) // pitch)
            means = []
            for j in range(ncy):
                for i in range(ncx):
                    cy = int(oy + (j + 0.5) * pitch)
                    cx = int(ox + (i + 0.5) * pitch)
                    means.append(gray[cy, cx])
            means = np.array(means)
            # bimodal sharpness: fraction clearly light or clearly dark
            crisp = np.mean((means > thresh + 30) | (means < thresh - 30))
            if crisp > best[2]:
                best = (ox, oy, crisp)
    return best[0], best[1]


def occupancy(gray, pitch, ox, oy, inset, thresh):
    """Sample an inset patch of each cell; floor if median brightness > thresh."""
    h, w = gray.shape
    ncx = int((w - ox) // pitch)
    ncy = int((h - oy) // pitch)
    grid = np.zeros((ncy, ncx), dtype=bool)
    pad = pitch * inset
    for j in range(ncy):
        for i in range(ncx):
            y0 = int(oy + j * pitch + pad)
            y1 = int(oy + (j + 1) * pitch - pad)
            x0 = int(ox + i * pitch + pad)
            x1 = int(ox + (i + 1) * pitch - pad)
            patch = gray[y0:y1, x0:x1]
            if patch.size == 0:
                continue
            grid[j, i] = np.median(patch) > thresh
    return grid


def render_ascii(grid):
    ncy, ncx = grid.shape
    out = []
    # top ruler: tens then ones
    tens = "    " + "".join(str((i // 10) % 10) if i % 10 == 0 else " " for i in range(ncx))
    ones = "    " + "".join(str(i % 10) for i in range(ncx))
    out.append(tens)
    out.append(ones)
    for j in range(ncy):
        row = "".join(" " if grid[j, i] else "." for i in range(ncx))
        out.append(f"{j:3d} {row}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--cols", type=int, default=30, help="cell columns across")
    ap.add_argument("--inset", type=float, default=0.28, help="fraction trimmed per side when sampling a cell")
    ap.add_argument("--thresh", type=float, default=150.0, help="brightness split floor/rock (0-255)")
    args = ap.parse_args()

    gray, (w, h) = load_gray(args.image)
    pitch = guess_pitch(w, h, args.cols)
    ox, oy = calibrate_origin(gray, pitch, args.thresh)
    grid = occupancy(gray, pitch, ox, oy, args.inset, args.thresh)
    ncy, ncx = grid.shape

    print(f"# image {w}x{h}px  pitch={pitch:.2f}px  origin=({ox:.1f},{oy:.1f})", file=sys.stderr)
    print(f"# grid {ncx} x {ncy} cells  floor cells={int(grid.sum())}", file=sys.stderr)
    print(render_ascii(grid))


if __name__ == "__main__":
    main()
