"""Cut the Stonehell symbol templates from known pages.

Each template is a window across one lattice line, `2*across+1` px wide and
`2*along+1` px along the line, taken from a page with dark text blanked
(prep's `work/notext.png`). A vertical-line window is stored as-is; a
horizontal line's window is transposed, so every template reads the same way.
Symbols that turn with their line (door boxes, arch ticks) match on both
orientations from one template; letters don't turn (an "S" is printed upright
on any line), so they get one template per orientation — `orient` in
style.json.

    page 73 (Level 1A)
      door    the door on 10's west wall              x=722, y=45   vertical
      S       the secret door east of 28              x=210, y=767  vertical
      arch    the northern archway at A               y=271, x=406  horizontal
      plain   an ordinary grid line, row-1 corridor   x=60,  y=45   vertical
      plain_x an ordinary grid *crossing*, inside 1   x=421, y=421  vertical
              (a symbol centred on a lattice point, like arch2, must beat a
              plain crossing, not just a plain line — the crossing line
              looks like its ticks)
    page 77 (Level 1B)
      S_h     the secret door on 5's north wall       y=150, x=495  horizontal
      arch2   15's north archway, two cells wide      y=541, x=751  horizontal

Add a symbol: pick a clean instance, add a line here, give it a door type (and
`orient` if it's a letter) in style.json's "templates", re-run.

    uv run --with pillow --with numpy python make_templates.py 73=PATH/notext.png 77=PATH/notext.png
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

A, L = 12, 13
CUTS = {
    "door": ("73", "v", 722, 45),
    "S": ("73", "v", 210, 767),
    "arch": ("73", "h", 271, 406),
    "plain": ("73", "v", 60, 45),
    "plain_x": ("73", "v", 421, 421),
    "S_h": ("77", "h", 150, 495),
    "arch2": ("77", "h", 541, 751),
}

pages = dict(a.split("=", 1) for a in sys.argv[1:])
for name, (page, o, a, b) in CUTS.items():
    if page not in pages:
        print(f"skip {name}: no page {page} given")
        continue
    g = np.asarray(Image.open(pages[page]).convert("L"))
    img = g if o == "v" else g.T
    win = img[b - L:b + L + 1, a - A:a + A + 1]
    Image.fromarray(win).save(Path(__file__).parent / f"{name}.png")
    print(name, win.shape)
