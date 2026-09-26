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
    # floor is told apart from rock by colour, so rock must not be white: a map
    # without a background (most hand-made ones) would otherwise score as all floor
    dmap.map.background = "#CCC"
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
            lab[f"room.{n}"] = m.group(1).upper()   # "Ucpt" in one map is "UCpt" in another
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
    # a page can be a pixel taller than its square grid (page 82 is 902x903): compare the shared area
    h, w = min(rf.shape[0], rock.shape[0]), min(rf.shape[1], rock.shape[1])
    rf, rock = rf[:h, :w], rock[:h, :w]
    sf = ~rock
    iou = float((rf & sf).sum() / (rf | sf).sum())
    o = np.asarray(Image.open(job.image).convert("RGB"))[:h, :w].copy()
    o[sf & ~rf] = [230, 0, 0]
    o[rf & ~sf] = [0, 90, 255]
    Image.fromarray(o).save(job.work / "diff.png")

    dmap = parse(src, path=job.dmap)
    diags = validate(dmap)
    errors = [d.message for d in diags if d.severity == "error"]
    warnings = [d.message for d in diags if d.severity == "warning"]
    reviewed = review_warnings(job, dmap, warnings)
    out = {"iou": round(iou, 3), "errors": errors, "warnings": reviewed}

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
        riou, roff = _ref_iou(refp, rock, sf, job.grid()[1])
        out["reference_iou"], out["reference_offset"] = round(riou, 3), roff
    save_json(job.work / "score.json", out)
    t = out.get("topology")
    print(f"score: IoU {out['iou']}" + (f" (reference {out['reference_iou']})" if t else "")
          + f", {len(errors)} errors, {len(warnings)} warnings"
          + (f", topology shared {t['shared']} / auto {t['auto_pairs']} / ref {t['ref_pairs']}" if t else ""))
    for e in errors:
        print("  error:", e)
    unexpected = [w for w in reviewed if not w.get("expected")]
    for w in reviewed:
        tag = f"expected — {w['expected']}" if w.get("expected") else "UNEXPECTED — fix it, or add to job.json expected_warnings"
        print(f"  warning: {w['message']}" + (f" [at {w['at']}]" if w.get("at") else "") + f"  ({tag})")
    out["rc"] = 1 if errors or unexpected else 0
    return out


def _corridor_centre(dmap, name: str):
    c = dmap.corridors.get(name)
    if c is None:
        return None
    pts = [tuple(p) for p in getattr(c, "nodes", {}).values()] if isinstance(getattr(c, "nodes", None), dict) else []
    if not pts:
        pts = [tuple(s.start) for s in c.segments] + [tuple(s.end) for s in c.segments]
    return [round(sum(x for x, _ in pts) / len(pts), 1), round(sum(y for _, y in pts) / len(pts), 1)]


def review_warnings(job: Job, dmap, warnings: list[str]) -> list[dict]:
    """Every warning is a decision: fixed, or listed in job.json `expected_warnings`
    with a reason. Generated names (c50) change between builds, so an expectation
    names a place, not a corridor:

        {"dead_end_at": [x, y], "why": "…"}        a dead-end corridor within 1.5 cells
        {"disconnected": "room.r24", "why": "…"}   a separate part containing this node
        {"match": "text", "why": "…"}               any warning containing the text
    """
    exp = job.cfg.get("expected_warnings", [])
    out = []
    for w in warnings:
        rec: dict = {"message": w}
        m = re.match(r"corridor '([^']+)' has only one door", w)
        if m:
            rec["at"] = _corridor_centre(dmap, m.group(1))
        for e in exp:
            if "dead_end_at" in e and rec.get("at") and \
                    abs(rec["at"][0] - e["dead_end_at"][0]) + abs(rec["at"][1] - e["dead_end_at"][1]) <= 1.5:
                rec["expected"] = e["why"]
            elif "disconnected" in e and w.startswith("map is not connected") and e["disconnected"] in w:
                rec["expected"] = e["why"]
            elif "match" in e and e["match"] in w:
                rec["expected"] = e["why"]
            if rec.get("expected"):
                break
        out.append(rec)
    return out


def _ref_iou(refp: Path, rock, sf, pitch: float) -> tuple[float, list[float]]:
    """The reference's floor against the page, at the page's own scale. A hand-made
    map may use a bigger grid with a margin (1D is 31x31 so wall edges stay clear of
    the border): it's rendered at `pitch` px per cell whatever its bounds, then the
    best offset within ±1.5 cells (half-cell steps) is taken. Returns (IoU, offset)."""
    from dungml import parse
    src = re.sub(r"(?m)^\s*(renderer|cell_grid) .*$", "", refp.read_text())
    g = parse(src, path=refp).map.grid
    bw, bh = int(round(g.bounds_w)), int(round(g.bounds_h))
    a = render_png(src, refp, int(round(max(bw, bh) * pitch)))
    rf = a.mean(2) > 215
    holes = nd.binary_fill_holes(rf) & ~rf
    hl, hn = nd.label(holes)
    rf |= np.isin(hl, 1 + np.where(nd.sum(holes, hl, range(1, hn + 1)) < 900)[0])
    rf = nd.binary_dilation(rf, np.ones((5, 5)))
    best = (0.0, [0.0, 0.0])
    for dy in np.arange(-1.5, 2.0, 0.5):
        for dx in np.arange(-1.5, 2.0, 0.5):
            # page pixel p shows reference pixel p + offset
            oy, ox = int(round(dy * pitch)), int(round(dx * pitch))
            ref = np.zeros_like(sf)
            ys, xs = slice(max(0, -oy), min(sf.shape[0], rf.shape[0] - oy)), slice(max(0, -ox), min(sf.shape[1], rf.shape[1] - ox))
            ref[ys, xs] = rf[ys.start + oy:ys.stop + oy, xs.start + ox:xs.stop + ox]
            iou = float((ref & sf).sum() / (ref | sf).sum())
            if iou > best[0]:
                best = (iou, [float(dx), float(dy)])
    return best
