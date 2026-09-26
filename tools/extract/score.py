"""Step 5 — how good is the map? Floor overlap, validation, and topology.

* **IoU**: the rendered map's floor against the page's floor (not rock). The
  map is rendered with labels stripped and room numbers off, because labels
  render as white halos that would count as floor.
* **validate**: `dungml` diagnostics (errors fail the step).
* **topology** (when job.json names a `reference` map): which labelled rooms
  reach which through corridors and unlabelled space only, compared pair by
  pair. Rooms named `r27a`… (sub-rooms without their own label) fold into
  their parent as `27*`.

Writes work/score.json and work/diff.png (red: page floor the map misses;
blue: map floor over the page's rock).
"""
from __future__ import annotations

import re
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as nd

from common import Job, save_json


def render_png(src: str, path: Path, px: int) -> np.ndarray:
    import cairosvg
    from dungml import parse
    from dungml.render import get_renderer
    src = re.sub(r"(?m)^\s*label .*$", "", src)
    dmap = parse(src, path=path)
    dmap.map.room_numbers = False
    svg = get_renderer("classic-bw")().render(dmap)
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=px, output_height=px)
    import io
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), float)


def room_graph(path: Path) -> dict:
    from dungml import build_graph, parse
    src = path.read_text()
    g = build_graph(parse(src, path=path))
    lab = {}
    for n, body in re.findall(r'(?ms)^room "([^"]+)"\s*\{(.*?)^\}', src):
        m = re.search(r'(?m)^\s*label "([^"]+)"', body)
        if m and f"room.{n}" in g.nodes:
            lab[f"room.{n}"] = m.group(1)
    for nid in g.nodes:
        if (m := re.fullmatch(r"room\.r(\d+)[a-z]", nid)) and nid not in lab:
            lab[nid] = m.group(1) + "*"
    pairs = set()
    for s, L in lab.items():
        q, seen = deque([s]), {s}
        while q:
            n = q.popleft()
            for nb, _e in g.neighbors(n):
                if nb in seen:
                    continue
                if nb in lab:
                    if lab[nb] != L:
                        pairs.add(tuple(sorted((L, lab[nb]))))
                    continue
                seen.add(nb)
                q.append(nb)
    return {"pairs": pairs, "labels": sorted(set(lab.values()))}


def main(job: Job) -> dict:
    from dungml import parse
    from dungml.validate import validate
    src = job.dmap.read_text()
    rock = np.load(job.work / "rock.npy")
    a = render_png(src, job.dmap, rock.shape[1])
    rf = a.mean(2) > 215
    holes = nd.binary_fill_holes(rf) & ~rf
    hl, hn = nd.label(holes)
    sz = nd.sum(holes, hl, range(1, hn + 1))
    rf |= np.isin(hl, 1 + np.where(sz < 900)[0])          # symbols drawn on the floor
    rf = nd.binary_dilation(rf, np.ones((5, 5)))           # floor fill stops at the wall's inner edge
    sf = ~rock
    iou = float((rf & sf).sum() / (rf | sf).sum())
    o = np.asarray(Image.open(job.image).convert("RGB")).copy()
    o[sf & ~rf] = [230, 0, 0]
    o[rf & ~sf] = [0, 90, 255]
    Image.fromarray(o).save(job.work / "diff.png")

    diags = validate(parse(src, path=job.dmap))
    errors = [d.message for d in diags if d.severity == "error"]
    warnings = [d.message for d in diags if d.severity == "warning"]
    out = {"iou": round(iou, 3), "errors": errors, "warnings": warnings}

    if ref := job.cfg.get("reference"):
        refp = Path(ref).expanduser()
        refp = refp if refp.is_absolute() else (job.dir / refp).resolve()
        A, B = room_graph(job.dmap), room_graph(refp)
        out["topology"] = {
            "auto_pairs": len(A["pairs"]), "ref_pairs": len(B["pairs"]),
            "shared": len(A["pairs"] & B["pairs"]),
            "only_auto": sorted(A["pairs"] - B["pairs"]), "only_ref": sorted(B["pairs"] - A["pairs"]),
            "labels_only_in_ref": sorted(set(B["labels"]) - set(A["labels"])),
        }
        out["reference_iou"] = round(_ref_iou(refp, rock, sf), 3)
    save_json(job.work / "score.json", out)
    t = out.get("topology")
    print(f"score: IoU {out['iou']}" + (f" (reference {out['reference_iou']})" if t else "")
          + f", {len(errors)} errors, {len(warnings)} warnings"
          + (f", topology shared {t['shared']} / auto {t['auto_pairs']} / ref {t['ref_pairs']}" if t else ""))
    for e in errors:
        print("  error:", e)
    return out


def _ref_iou(refp: Path, rock, sf) -> float:
    a = render_png(re.sub(r"(?m)^\s*(renderer|cell_grid) .*$", "", refp.read_text()), refp, rock.shape[1])
    rf = a.mean(2) > 215
    holes = nd.binary_fill_holes(rf) & ~rf
    hl, hn = nd.label(holes)
    rf |= np.isin(hl, 1 + np.where(nd.sum(holes, hl, range(1, hn + 1)) < 900)[0])
    rf = nd.binary_dilation(rf, np.ones((5, 5)))
    return float((rf & sf).sum() / (rf | sf).sum())
