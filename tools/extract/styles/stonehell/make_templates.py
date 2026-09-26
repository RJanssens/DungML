"""Cut the Stonehell symbol templates from page 73 (Level 1A).

Each template is a window across one lattice line, `2*across+1` px wide and
`2*along+1` px along the line, taken from the page with dark text blanked
(prep's `notext.png`). Vertical-line windows are stored as-is; a horizontal
line's window is transposed so every template reads the same way.

    door   the door on 10's west wall          (x=722, y=45,  vertical line)
    S      the secret door east of 28          (x=210, y=767, vertical line)
    arch   the northern archway at A           (y=271, x=406, horizontal line)
    plain  an ordinary grid line, row-1 corridor (x=60, y=45,  vertical line)

Re-run to add a symbol: pick a clean instance, add a line here, and give it a
door type in style.json's "templates".

    uv run --with pillow --with numpy python make_templates.py PATH/TO/73/work/notext.png
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

A, L = 12, 13
CUTS = {
    "door": ("v", 722, 45),
    "S": ("v", 210, 767),
    "arch": ("h", 271, 406),
    "plain": ("v", 60, 45),
}

g = np.asarray(Image.open(sys.argv[1]).convert("L"))
for name, (o, a, b) in CUTS.items():
    img = g if o == "v" else g.T
    win = img[b - L:b + L + 1, a - A:a + A + 1]
    Image.fromarray(win).save(Path(__file__).parent / f"{name}.png")
    print(name, win.shape)
