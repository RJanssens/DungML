"""Step 4 — turn cells, labels and symbols into a .dmap.

Reads work/ (prep, symbols), labels.json, corrections.json, descriptions.json
(optional) and writes `<name>.dmap` in the job folder.

How floor becomes rooms, caves and corridors:

* A cell is floor if enough of it isn't rock; a partial cell whose rock/floor
  boundary isn't one straight 0/45/90° line is *organic* (a cave wall).
* Caves: floor near organic cells, split between the labels inside it by
  distance. A label whose largest full-floor rectangle is walled by rock or
  openings (not ringed by partial cells) is a room even if it sits next to a
  cave, and its rectangle is carved out first.
* Rooms: the largest full-floor rectangle around each room label that crosses
  no door or wall (corners may be chamfered: octagons, diagonal walls). A
  1-wide strip only if nothing wider fits. Partial cells hugging it join it.
* Corridors: all remaining floor, split at doors, walls and junctions (so fog
  reveals a corridor up to the next branching). A corridor piece that only
  opens onto one room is a bump of that room (L-shaped rooms).
* Connections: every stretch of boundary between two spaces is a door — the
  detected symbol there, or `open` where floor actually crosses the edge.

Every feature is emitted *inside* the room or corridor it stands in, so fog
of war hides it with its space; a key title goes to dm_notes, not the
read-aloud description, since titles give things away ("Gas Fountain").
"""
from __future__ import annotations

import re
from collections import defaultdict, deque

import numpy as np
from PIL import Image
from scipy import ndimage as nd
from skimage import measure

from common import Job, ekey, fmt, load_json, nbrs as _nbrs, save_json


def main(job: Job) -> None:  # noqa: C901 — one pass, read top to bottom
    st, cfg = job.style, job.cfg
    N, P = job.grid()
    g = job.gray()
    gt = np.asarray(Image.open(job.work / "notext.png"), float)
    frac = np.load(job.work / "frac.npy")
    rock = np.load(job.work / "rock.npy")
    corr = job.corrections()
    FULL = st["full_frac"]
    F = frac > st["floor_min_frac"]
    for i, j in corr.get("not_floor", []):
        F[i, j] = False

    def nbrs(i, j):
        return _nbrs(i, j, N)

    # ------------------------------------------------------------ grid lines
    def edge_strip(i, j, d, half=3):
        if d == "r":
            x = int(round((j + 1) * P))
            return gt[int(i * P) + 6:int((i + 1) * P) - 6, x - half:x + half + 1]
        y = int(round((i + 1) * P))
        return gt[y - half:y + half + 1, int(j * P) + 6:int((j + 1) * P) - 6].T

    gridded = np.zeros((N, N), bool)
    for i in range(N):
        for j in range(N):
            for d, ii, jj in list(nbrs(i, j))[:2]:
                if F[i, j] and F[ii, jj] and np.median(edge_strip(i, j, d).min(1)) < st["gridline_max"]:
                    gridded[i, j] = gridded[ii, jj] = True

    def organic_cell(i, j):
        # partial cell: is the rock/floor boundary one straight (0/45/90°) line?
        y0, y1 = int(round(i * P)), int(round((i + 1) * P))
        x0, x1 = int(round(j * P)), int(round((j + 1) * P))
        r = rock[y0:y1, x0:x1]
        ys, xs = np.nonzero(r & ~nd.binary_erosion(r, np.ones((3, 3)), border_value=1))
        if len(xs) < 8:
            return False
        pts = np.c_[xs, ys].astype(float)
        pts -= pts.mean(0)
        _, sv, vt = np.linalg.svd(pts, full_matrices=False)
        ang = np.degrees(np.arctan2(vt[0, 1], vt[0, 0])) % 45
        return sv[1] / np.sqrt(len(pts)) > 1.6 or min(ang, 45 - ang) > 8

    organic = np.zeros((N, N), bool)
    for i in range(N):
        for j in range(N):
            if F[i, j] and frac[i, j] < FULL:
                organic[i, j] = organic_cell(i, j)
    cave = F & nd.binary_dilation(organic, np.ones((3, 3)))

    # ------------------------------------------------------------ doors / walls
    hits = [h for h in load_json(job.work / "symbols.json") if h["s"] >= corr.get("door_threshold", 0)]

    def roomlike(c):
        # inside a 2x2 block of full floor: part of a room, not a 1-wide passage
        i, j = c
        return any(all(0 <= i + di + a < N and 0 <= j + dj + b < N and frac[i + di + a, j + dj + b] >= FULL
                       for a in (0, 1) for b in (0, 1)) for di, dj in ((0, 0), (-1, 0), (0, -1), (-1, -1)))

    def hit_edges(h):
        if h.get("mid"):
            # drawn across the middle of a one-cell passage: put it on the wall where the
            # passage meets the room, so it renders on a wall and blocks the same way
            r, c = h["cell"]
            if h["o"] == "v":
                sides = [((r, c - 1), (r, c), (c, r + .5)), ((r, c), (r, c + 1), (c + 1, r + .5))]
                outer = [(r, c - 1), (r, c + 1)]
            else:
                sides = [((r - 1, c), (r, c), (c + .5, r)), ((r, c), (r + 1, c), (c + .5, r + 1))]
                outer = [(r - 1, c), (r + 1, c)]
            k = 1 if roomlike(outer[1]) and not roomlike(outer[0]) else 0
            if not roomlike(outer[0]) and not roomlike(outer[1]):
                k = 1
            a, b, pos = sides[k]
            return [ekey(a, b)], pos
        k, p = h["k"], h["p"] / P
        m = round(p)
        rows = [m - 1, m] if abs(p - m) < 0.2 else [int(p)]   # a door centred on a lattice point spans two edges
        es = []
        for r in rows:
            a, b = ((r, k - 1), (r, k)) if h["o"] == "v" else ((k - 1, r), (k, r))
            if 0 <= min(a + b) and max(a + b) < N:
                es.append(ekey(a, b))
        pos = (k, round(p * 2) / 2) if h["o"] == "v" else (round(p * 2) / 2, k)
        return es, pos

    doors = []
    # a symbol false positive (1C's "!" spear trap): {"at": [x, y], "type": "wooden"}; the type
    # matters when a real symbol lands on the same wall (30's secret door beside the "!")
    drop = [(tuple(p["at"]), p.get("type")) if isinstance(p, dict) else (tuple(p), None)
            for p in corr.get("not_doors", [])]
    for h in hits:
        es, pos = hit_edges(h)
        if any(abs(pos[0] - x) + abs(pos[1] - y) <= 0.8 and t in (None, h["type"]) for (x, y), t in drop):
            continue
        doors.append(dict(edges=es, pos=pos, type=h["type"], width=h.get("width", 1),
                          **({"state": h["state"]} if h.get("state") else {})))
    for c in corr.get("extra_doors", []):
        d = dict(edges=[ekey(tuple(a), tuple(b)) for a, b in c["edges"]], pos=tuple(c["pos"]), type=c["type"],
                 width=c.get("width", 1))
        d.update({k: tuple(c[k]) if k == "from" else c[k] for k in ("from", "state") if k in c})
        doors.append(d)
    for c in corr.get("retype", []):
        for d in doors:
            if tuple(d["pos"]) == tuple(c["pos"]):
                d["type"] = c["type"]
                d.update({k: tuple(c[k]) if k == "from" else c[k] for k in ("from", "state") if k in c})
    door_edge = {e: n for n, d in enumerate(doors) for e in d["edges"]}
    mid_cells = {tuple(h["cell"]) for h in hits if h.get("mid")}
    for c in mid_cells:
        # a filled locked door is rock-grey and can cover most of a narrow passage cell,
        # but a cell with a door drawn across it is floor
        F[c] = True
    walls = {ekey(tuple(a), tuple(b)) for a, b in corr.get("walls", [])}
    # drawn walls between two floor cells: a grid line is 0-1 px of mid grey
    # (min ~170); a wall is 2+ px darker than 170 with a minimum under 150,
    # floor on both sides (measured on pages 73 and 77)
    not_walls = {ekey(tuple(a), tuple(b)) for a, b in corr.get("not_walls", [])}
    detected_walls = set()
    for i in range(N):
        for j in range(N):
            for d, ii, jj in list(nbrs(i, j))[:2]:
                e = ekey((i, j), (ii, jj))
                if not (F[i, j] and F[ii, jj]) or e in door_edge or e in not_walls:
                    continue
                prof = np.median(edge_strip(i, j, d, half=5), axis=0)
                if prof.min() < 150 and (prof < 170).sum() >= 2 and prof[0] > 200 and prof[-1] > 200:
                    detected_walls.add(e)

    def vertex_cells(vi, vj):
        return [(vi + a, vj + b) for a in (-1, 0) for b in (-1, 0) if 0 <= vi + a < N and 0 <= vj + b < N]

    def ends(e):
        (i, j), (ii, jj) = e
        return [(i, j + 1), (i + 1, j + 1)] if ii == i else [(i + 1, j), (i + 1, j + 1)]   # lattice vertices

    def anchored(e, cand):
        # a drawn wall runs into rock or into another wall; an icon's outline (an
        # altar box, stair treads, grey lettering) floats in open floor
        for v in ends(e):
            if any(not F[c] for c in vertex_cells(*v)):
                return True
            if any(f != e and v in ends(f) for f in cand):
                return True
        return False

    changed = True
    while changed:                         # drop floating candidates until only anchored ones remain
        changed = False
        for e in list(detected_walls):
            if not anchored(e, detected_walls):
                detected_walls.discard(e)
                changed = True
    walls |= detected_walls
    blocked = set(door_edge) | walls

    def open_between(a, b):
        return ekey(a, b) not in blocked

    # ------------------------------------------------------------ labels
    boxes = load_json(job.work / "boxes.json")
    texts = load_json(job.dir / "labels.json")
    if len(texts) != len(boxes):
        raise SystemExit(f"labels.json has {len(texts)} entries for {len(boxes)} boxes")
    room_re = re.compile(st["room_label"])
    labels, label_box = {}, {}
    for box, t in zip(boxes, texts):
        if room_re.match(t or ""):
            x0, y0, x1, y1 = box
            label_box[t] = box
            labels[t] = (int(((y0 + y1) / 2) // P), int(((x0 + x1) / 2) // P))
    for nm, cell in corr.get("label_cell", {}).items():   # a label detection missed, or printed outside its room
        labels[nm] = tuple(cell)
        if nm not in label_box:
            i, j = cell
            label_box[nm] = [j * P + P * .2, i * P + P * .2, (j + 1) * P - P * .2, (i + 1) * P - P * .2]
    # label rooms: a label text that marks many rooms sharing one key entry
    # (Stonehell's Cpt/UCpt crypts) — each becomes a room of its own, Cpt1, Cpt2…
    label_room_of: dict[str, str] = {}
    counts: dict[str, int] = defaultdict(int)
    for box, t in zip(boxes, texts):
        if t in cfg.get("label_rooms", []):
            counts[t] += 1
            nm = f"{t}{counts[t]}"
            x0, y0, x1, y1 = box
            label_box[nm] = box
            labels[nm] = (int(((y0 + y1) / 2) // P), int(((x0 + x1) / 2) // P))
            label_room_of[nm] = t

    region = -np.ones((N, N), int)
    regions: list[dict] = []

    # ------------------------------------------------------------ caves
    full = F & (frac >= FULL)

    def best_full_rect(si, sj, R=5):
        best = None
        for i0 in range(si - R, si + 1):
            for j0 in range(sj - R, sj + 1):
                for i1 in range(si, si + R + 1):
                    for j1 in range(sj, sj + R + 1):
                        if i0 < 0 or j0 < 0 or i1 >= N or j1 >= N:
                            continue
                        if full[i0:i1 + 1, j0:j1 + 1].all():
                            a = (i1 - i0 + 1) * (j1 - j0 + 1)
                            if best is None or a > best[0]:
                                best = (a, (i0, j0, i1, j1))
        return best

    def partial_share(r):
        i0, j0, i1, j1 = r
        ring = [(i0 - 1, j) for j in range(j0, j1 + 1)] + [(i1 + 1, j) for j in range(j0, j1 + 1)]
        ring += [(i, j0 - 1) for i in range(i0, i1 + 1)] + [(i, j1 + 1) for i in range(i0, i1 + 1)]
        ring = [c for c in ring if 0 <= c[0] < N and 0 <= c[1] < N]
        return sum(0.05 < frac[c] < FULL for c in ring) / len(ring)

    cave_label = {}
    for nm, (i, j) in labels.items():
        b = best_full_rect(i, j)
        org3 = organic[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2].sum()
        cave_label[nm] = bool(cave[i, j]) and not (b and partial_share(b[1]) <= 0.15 and org3 < 3) \
            and nm not in corr.get("not_cave", [])      # icon line-work (a spiral stair) can look organic
        if nm in corr.get("cave", []):                  # a cave label in a flat, walled-looking pocket
            cave_label[nm] = True
            cave[i, j] = True
    for nm, (i, j) in labels.items():
        b = best_full_rect(i, j)
        if not cave_label[nm] and b and min(b[1][2] - b[1][0], b[1][3] - b[1][1]) >= 1:
            i0, j0, i1, j1 = b[1]
            cave[i0:i1 + 1, j0:j1 + 1] = False       # a walled room next to a cave isn't cave
    q = deque()
    for nm, c in labels.items():
        if cave[c] and nm not in corr.get("not_cave", []):
            regions.append(dict(kind="cave", name=nm, cells=[]))
            region[c] = len(regions) - 1
            q.append(c)
    while q:
        a = q.popleft()
        for _, ii, jj in nbrs(*a):
            if cave[ii, jj] and region[ii, jj] < 0 and open_between(a, (ii, jj)):
                region[ii, jj] = region[a]
                q.append((ii, jj))
    cave &= region >= 0      # organic-looking art no cave label reaches (arrows, compass)

    # ------------------------------------------------------------ rooms
    def rect_ok(i0, j0, i1, j1):
        if i0 < 0 or j0 < 0 or i1 >= N or j1 >= N:
            return False
        fl = frac[i0:i1 + 1, j0:j1 + 1] >= FULL
        for ci, cj in ((0, 0), (0, -1), (-1, 0), (-1, -1)):
            fl[ci, cj] = True                          # chamfered corners
        blk = F[i0:i1 + 1, j0:j1 + 1] & gridded[i0:i1 + 1, j0:j1 + 1] & (region[i0:i1 + 1, j0:j1 + 1] < 0) & fl
        if not blk.all():
            return False
        return all(open_between((i, j), (i, j + 1)) for i in range(i0, i1 + 1) for j in range(j0, j1)) and \
            all(open_between((i, j), (i + 1, j)) for i in range(i0, i1) for j in range(j0, j1 + 1))

    for nm, cells in corr.get("extra_rooms", {}).items():
        regions.append(dict(kind="room", name=nm, cells=[]))
        for i, j in cells:
            region[i, j] = len(regions) - 1
    rects = {}
    for nm, (si, sj) in sorted(((nm, c) for nm, c in labels.items() if not cave[c]),
                               key=lambda t: (len(t[0]), t[0])):
        if nm in corr.get("room_rect", {}):
            rects[nm] = tuple(corr["room_rect"][nm])
            continue
        best, R = None, 6
        for i0 in range(si - R, si + 1):
            for j0 in range(sj - R, sj + 1):
                for i1 in range(si, si + R + 1):
                    for j1 in range(sj, sj + R + 1):
                        area = (i1 - i0 + 1) * (j1 - j0 + 1)
                        thin = min(i1 - i0, j1 - j0) < 1
                        if thin and area > 2:          # 1-wide: only a small room when nothing wider fits
                            continue
                        key = (not thin, area, -abs((i1 - i0) - (j1 - j0)))
                        if (best is None or key > best[0]) and rect_ok(i0, j0, i1, j1):
                            best = (key, (i0, j0, i1, j1))
        rects[nm] = best[1] if best else (si, sj, si, sj)
    for nm, (i0, j0, i1, j1) in sorted(rects.items(), key=lambda t: -(t[1][2] - t[1][0] + 1) * (t[1][3] - t[1][1] + 1)):
        regions.append(dict(kind="room", name=nm, cells=[]))
        rid = len(regions) - 1
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                if region[i, j] < 0:
                    region[i, j] = rid
        for i in range(i0 - 1, i1 + 2):
            for j in range(j0 - 1, j1 + 2):
                # edge-adjacent to the rectangle only: a cell touching it corner-to-corner is
                # a neighbour's chamfer (1C: 5 took one of octagon 16's diagonal cells)
                beside = (i0 <= i <= i1) != (j0 <= j <= j1)
                if beside and 0 <= i < N and 0 <= j < N and F[i, j] and region[i, j] < 0 and frac[i, j] < FULL \
                        and (i, j) not in mid_cells:   # a passage with a portcullis's dots isn't a chamfer
                    region[i, j] = rid

    # ------------------------------------------------------------ corridors
    for i in range(N):
        for j in range(N):
            if F[i, j] and region[i, j] < 0:
                regions.append(dict(kind="corridor", name=f"c{len(regions)}", cells=[]))
                rid = len(regions) - 1
                region[i, j] = rid
                q = deque([(i, j)])
                while q:
                    a = q.popleft()
                    for _, ii, jj in nbrs(*a):
                        if F[ii, jj] and region[ii, jj] < 0 and not cave[ii, jj] and open_between(a, (ii, jj)):
                            region[ii, jj] = rid
                            q.append((ii, jj))

    def cells_of(rid):
        return [tuple(c) for c in zip(*np.nonzero(region == rid))]

    changed = True
    while changed:                      # bumps: a corridor piece that only opens onto one room
        changed = False
        for rid, r in enumerate(regions):
            if r["kind"] != "corridor" or not (cells := cells_of(rid)):
                continue
            touch = [{region[ii, jj] for _, ii, jj in nbrs(*c)
                      if region[ii, jj] >= 0 and region[ii, jj] != rid and open_between(c, (ii, jj))} for c in cells]
            outside = set().union(*touch)
            # every cell flush against the host — or a small pocket (≤ 4 cells) whose
            # far cell hangs off the flush ones (1B's octagon edge + statue alcove)
            if len(outside) != 1 or not (all(touch) or len(cells) <= 4):
                continue
            host = outside.pop()
            # rooms and caves take a bump of any size (the L of #3, a cave's stray
            # floor); a corridor takes a pocket of one or two cells (a statue alcove),
            # which lets the pocket chain on into the room it hangs off (1B's 4)
            if regions[host]["kind"] in ("room", "cave") or (regions[host]["kind"] == "corridor" and len(cells) <= 2):
                for c in cells:
                    region[c] = host
                changed = True

    def same(rid, a, b):
        return region[b] == rid and open_between(a, b)

    def in_blob(rid, c):
        i, j = c
        return any(all(0 <= i + di + a < N and 0 <= j + dj + b < N and region[i + di + a, j + dj + b] == rid
                       for a in (0, 1) for b in (0, 1)) for di, dj in ((0, 0), (-1, 0), (0, -1), (-1, -1)))

    for rid in [k for k, r in enumerate(regions) if r["kind"] == "corridor"]:   # split at junctions
        cells = cells_of(rid)
        junction = {c for c in cells if sum(same(rid, c, (ii, jj)) for _, ii, jj in nbrs(*c)) >= 3
                    and not in_blob(rid, c)}
        todo, first = set(cells), True
        while junction and todo:
            seed = min(todo)
            kj = seed in junction
            comp, q = {seed}, deque([seed])
            while q:
                a = q.popleft()
                for _, ii, jj in nbrs(*a):
                    b = (ii, jj)
                    if b in todo and b not in comp and (b in junction) == kj and same(rid, a, b):
                        comp.add(b)
                        q.append(b)
            todo -= comp
            if first:
                first = False
                continue
            regions.append(dict(kind="corridor", name=f"c{len(regions)}", cells=[]))
            for c in comp:
                region[c] = len(regions) - 1

    for i in range(N):
        for j in range(N):
            if region[i, j] >= 0:
                regions[region[i, j]]["cells"].append((i, j))

    def touches(r):
        rid = region[r["cells"][0]]
        return any(region[ii, jj] >= 0 and region[ii, jj] != rid for c in r["cells"] for _, ii, jj in nbrs(*c))

    keep = [r for r in regions if r["cells"] and not (r["kind"] == "corridor" and
            ((all(frac[c] < FULL for c in r["cells"]) and not mid_cells & set(r["cells"]))   # arrows, compass, art
             or not touches(r)))]                  # (a passage with a door drawn across it is real)

    def safe(name: str) -> str:
        # DSL names are identifiers: a correction's "21 secret" must not break the parse
        return re.sub(r"\W", "_", name)

    def ident(r):
        return f'corridor.{safe(r["name"])}' if r["kind"] == "corridor" else f'room.r{safe(r["name"])}'

    # ------------------------------------------------------------ geometry
    def cell_px_mask(cells):
        m = np.zeros(g.shape, bool)
        for i, j in cells:
            m[int(round(i * P)):int(round((i + 1) * P)), int(round(j * P)):int(round((j + 1) * P))] = True
        return m

    def contour_poly(cells, tol):
        near = {(i + di, j + dj) for i, j in cells for di in (-1, 0, 1) for dj in (-1, 0, 1)
                if 0 <= i + di < N and 0 <= j + dj < N and region[i + di, j + dj] < 0}
        m = nd.binary_opening(~rock & cell_px_mask(set(cells) | near), np.ones((3, 3)))
        lab, n = nd.label(m)
        if n == 0:
            return None
        m = np.pad(lab == 1 + int(np.argmax(nd.sum(m, lab, range(1, n + 1)))), 1)
        c = measure.approximate_polygon(max(measure.find_contours(m.astype(float), 0.5), key=len), tol)
        return [((x - 1) / P, (y - 1) / P) for y, x in c[:-1]]

    desc = load_json(job.dir / "descriptions.json", default={"rooms": {}, "features_key": {}, "traps": {}, "map": {}})

    def text_ref(ref):
        # "features_key.C" / "traps.Pit" / "stalls.G" point into descriptions.json, so
        # module text stays module text; anything else is literal
        if isinstance(ref, str) and "." in ref:
            a, b = ref.split(".", 1)
            if isinstance(desc.get(a), dict) and b in desc[a] and a not in ("rooms", "map"):
                return desc[a][b]
        return ref

    def text_block(key, text, indent="  "):
        text = (text or "").strip()
        if not text:
            return []
        assert '"""' not in text
        return [f'{indent}{key} """', "\n".join(indent + "  " + l for l in text.split("\n")), f'{indent}"""']

    def feature_lines(f, indent="  "):
        ref = f["type"] if "-" not in f["type"] else '"' + f["type"] + '"'
        head = f'{indent}feature {ref} at {fmt(f["at"][0])},{fmt(f["at"][1])}' + (f' scale {f["scale"]}' if "scale" in f else "")
        body = text_block("description", text_ref(f.get("description")), indent + "  ") \
            + text_block("dm_notes", text_ref(f.get("dm_notes")), indent + "  ")
        return [head + " {"] + body + [indent + "}"] if body else [head]

    features = list(corr.get("features", []))
    if corr.get("dots", True) and (job.work / "dots.json").exists():   # detected pillar dots
        drop = {tuple(p) for p in corr.get("not_dots", [])}
        features += [{"type": st.get("dot_feature", "pillar"), "at": p}
                     for p in load_json(job.work / "dots.json") if tuple(p) not in drop]
    # text for a space the key describes by feature letter (E's bricked-up alcoves) or an
    # exit stub: attached to whichever room/corridor holds the cell
    notes_in = defaultdict(lambda: {"description": [], "dm_notes": []})
    for rn in corr.get("region_notes", []):
        rid = region[tuple(rn["cell"])]
        for k in ("description", "dm_notes"):
            if rn.get(k):
                notes_in[rid][k].append(text_ref(rn[k]))

    # exits to other maps: `to` is a level id in the module's maps.json (the project map
    # name is looked up there); nested in the space they stand in, like features, so fog
    # hides an exit until its room or corridor is found
    registry = load_json(job.dir.parent / "maps.json", default={"levels": {}})["levels"]

    def exit_lines(x, indent="  "):
        to = registry.get(x["to"], {}).get("name", x["to"])
        land = x.get("land", [15, 15])
        lines = [f'{indent}exit at {fmt(x["at"][0])},{fmt(x["at"][1])} {{',
                 f'{indent}  to "{to}" at {fmt(land[0])},{fmt(land[1])}']
        if x.get("label"):
            lines.append(f'{indent}  label "{x["label"]}"')
        if x.get("secret"):
            lines.append(f"{indent}  secret")
        lines += text_block("description", text_ref(x.get("description")), indent + "  ")
        lines += text_block("dm_notes", text_ref(x.get("dm_notes")), indent + "  ")
        return lines + [indent + "}"]

    def host_of(x, y):
        rid = region[min(int(y), N - 1), min(int(x), N - 1)]
        if rid < 0 or regions[rid] not in keep:   # on a wall: nearest space
            rid = min((abs(ii + .5 - y) + abs(jj + .5 - x), region[ii, jj]) for ii in range(N) for jj in range(N)
                      if region[ii, jj] >= 0 and regions[region[ii, jj]] in keep)[1]
        return rid

    exits_in = defaultdict(list)
    for x in corr.get("exits", []):
        exits_in[host_of(*x["at"])].append(x)

    feats_in = defaultdict(list)
    for f in features:
        x, y = f["at"]
        rid = region[min(int(y), N - 1), min(int(x), N - 1)]
        if rid < 0 or regions[rid] not in keep:   # on a wall: nearest space
            rid = min((abs(ii + .5 - y) + abs(jj + .5 - x), region[ii, jj]) for ii in range(N) for jj in range(N)
                      if region[ii, jj] >= 0 and regions[region[ii, jj]] in keep)[1]
        feats_in[rid].append(f)

    out = [f'include "{inc}"' for inc in cfg.get("includes", ["core.dmap"])] + [""]
    out += [f'map "{cfg["title"]}" {{',
            f"  grid {{ cell 32 px units feet 5 bounds {N} x {N} origin top-left }}",
            f'  renderer "{cfg.get("renderer", "classic-bw")}"', "  room_numbers off",
            f'  background "{cfg.get("background", "#CCC")}"']
    out += text_block("description", desc["map"].get("description"))
    out += text_block("dm_notes", desc["map"].get("dm_notes"))
    out += ["}", ""]
    stats = defaultdict(int)
    stats["walls_detected"] = len(detected_walls)

    for r in keep:
        if r["kind"] == "corridor":
            continue
        cells = r["cells"]
        rows, cols = [c[0] for c in cells], [c[1] for c in cells]
        is_rect = len(cells) == (max(rows) - min(rows) + 1) * (max(cols) - min(cols) + 1) \
            and all(frac[c] >= FULL for c in cells)
        out.append(f'room "r{safe(r["name"])}" {{')
        if r["kind"] == "room" and is_rect:
            out.append(f"  rect {min(cols)},{min(rows)} {max(cols) - min(cols) + 1} x {max(rows) - min(rows) + 1}")
            stats["rect"] += 1
        else:
            poly = contour_poly(cells, 1.2 if r["kind"] == "room" else 2.5)
            if r["kind"] == "room":   # straight walls: snap to half cells
                poly = [(round(x * 2) / 2, round(y * 2) / 2) for x, y in poly]
                poly = [p for n, p in enumerate(poly) if p != poly[n - 1]]
            out.append("  polygon " + " ".join(f"({fmt(x)},{fmt(y)})" for x, y in poly))
            if r["kind"] == "cave":
                out.append("  line_style organic")
            stats["poly_" + r["kind"]] += 1
        if r["name"] in label_box:   # where the page prints it
            x0, y0, x1, y1 = label_box[r["name"]]
            shown = label_room_of.get(r["name"], r["name"])
            out.append(f'  label "{shown}" at {fmt((x0 + x1) / 2 / P)},{fmt((y0 + y1) / 2 / P)}')
        key = desc["rooms"].get(label_room_of.get(r["name"], r["name"]))
        extra = notes_in.get(region[cells[0]], {"description": [], "dm_notes": []})
        d_parts = ([key["description"]] if key else []) + extra["description"]
        n_parts = ([(key["title"] + ". " + key["dm_notes"]).strip()] if key else []) + extra["dm_notes"]
        d_txt, n_txt = " ".join(p for p in d_parts if p), " ".join(p for p in n_parts if p)
        out += text_block("description", d_txt)
        out += text_block("dm_notes", n_txt)
        stats["described"] += bool(key)
        for f in feats_in.get(region[cells[0]], []):
            out += feature_lines(f)
            stats["feature"] += 1
        for x in exits_in.get(region[cells[0]], []):
            out += exit_lines(x)
            stats["exit"] += 1
        out += ["}", ""]

    def pixel_open(a, b):
        # adjacent cells connect only if floor actually crosses the shared edge
        (i, j), (ii, jj) = a, b
        if ii == i:
            x = int(round(max(j, jj) * P))
            s = rock[int(i * P) + 3:int((i + 1) * P) - 3, x - 4:x + 5]
        else:
            y = int(round(max(i, ii) * P))
            s = rock[y - 4:y + 5, int(j * P) + 3:int((j + 1) * P) - 3].T
        return (~s.any(1)).mean() > 0.25

    openings = defaultdict(list)
    for i in range(N):
        for j in range(N):
            for _, ii, jj in list(nbrs(i, j))[:2]:
                a, b = region[i, j], region[ii, jj]
                if a >= 0 and b >= 0 and a != b and regions[a] in keep and regions[b] in keep:
                    e = ekey((i, j), (ii, jj))
                    if e in walls or (e not in door_edge and not pixel_open((i, j), (ii, jj))):
                        continue
                    openings[(min(a, b), max(a, b))].append(e)

    def edge_mid(e):
        (i, j), (ii, jj) = e
        return ((j + jj + 1) / 2, (i + ii + 1) / 2)

    stub, conns = defaultdict(list), []
    for (a, b), es in openings.items():
        groups: list[list] = []
        for e in sorted(es):                        # contiguous stretches are separate openings
            for gp in groups:
                if any(abs(edge_mid(e)[0] - edge_mid(f)[0]) + abs(edge_mid(e)[1] - edge_mid(f)[1]) <= 1.01 for f in gp):
                    gp.append(e)
                    break
            else:
                groups.append([e])
        for gp in groups:
            if ds := {door_edge[e] for e in gp if e in door_edge}:
                for dn in ds:
                    d = doors[dn]
                    conns.append(dict(a=a, b=b, pos=d["pos"], type=d["type"], frm=d.get("from"),
                                      state=d.get("state"), width=d.get("width", 1)))
            else:
                xs = [edge_mid(e) for e in gp]
                pos = (round(sum(x for x, _ in xs) / len(xs) * 2) / 2, round(sum(y for _, y in xs) / len(xs) * 2) / 2)
                conns.append(dict(a=a, b=b, pos=pos, type="open", width=len(gp)))
                for c in corr.get("retype", []):
                    if tuple(c["pos"]) == pos:
                        conns[-1].update(type=c["type"], state=c.get("state"), width=1)
            for e in gp:
                for cell in e:
                    if regions[region[cell]]["kind"] == "corridor":
                        stub[region[cell]].append((cell, edge_mid(e)))

    for r in keep:
        if r["kind"] != "corridor":
            continue
        rid = region[r["cells"][0]]
        cells = set(r["cells"])
        pos = {c: (c[1] + .5, c[0] + .5) for c in cells}
        runs = {frozenset((c, (ii, jj))) for c in cells for _, ii, jj in list(nbrs(*c))[:2]
                if (ii, jj) in cells and open_between(c, (ii, jj))}
        for c, pt in set(stub.get(rid, [])):
            pos[("e", pt)] = pt
            runs.add(frozenset((c, ("e", pt))))
        deg = defaultdict(set)
        for a_, b_ in runs:
            deg[a_].add(b_)
            deg[b_].add(a_)
        for c in sorted(cells):        # a run stops at a cell centre: carry dead ends to the far wall
            if len(nb := deg[c]) > 1:
                continue
            x, y = pos[c]
            if nb:
                ox, oy = pos[next(iter(nb))]
                d = max(abs(ox - x) + abs(oy - y), 1e-9)
                far = (x - (ox - x) / d * .5, y - (oy - y) / d * .5)
            else:
                pos[("s", c)] = (x, c[0])
                runs.add(frozenset((("s", c), c)))
                far = (x, c[0] + 1)
            pos[("f", c)] = far
            runs.add(frozenset((c, ("f", c))))
        adj = defaultdict(set)
        for a_, b_ in runs:
            adj[a_].add(b_)
            adj[b_].add(a_)

        def collinear(u, v, w):
            (ux, uy), (vx, vy), (wx, wy) = pos[u], pos[v], pos[w]
            return abs((vx - ux) * (wy - uy) - (vy - uy) * (wx - ux)) < 1e-9 and \
                (vx - ux) * (wx - vx) + (vy - uy) * (wy - vy) > 0

        changed = True
        while changed:                 # drop points in the middle of a straight run
            changed = False
            for v in list(adj):
                if len(adj[v]) == 2:
                    u, w = adj[v]
                    if collinear(u, v, w) and w not in adj[u]:
                        adj[u].discard(v); adj[w].discard(v)
                        adj[u].add(w); adj[w].add(u)
                        del adj[v]
                        changed = True
        order: list = []
        ends = sorted((v for v in adj if len(adj[v]) == 1), key=lambda v: pos[v][::-1]) or sorted(adj, key=lambda v: pos[v][::-1])
        for s0 in ends:
            stack = [s0]
            while stack:
                v = stack.pop()
                if v not in order:
                    order.append(v)
                    stack.extend(sorted((w for w in adj[v] if w not in order), key=lambda w: pos[w][::-1], reverse=True))
        name = {v: f"n{k + 1}" for k, v in enumerate(order)}
        out += [f'corridor "{r["name"]}" {{', "  width 1"]
        out += [f"  node {name[v]} at {fmt(pos[v][0])},{fmt(pos[v][1])}" for v in order]
        done = set()
        for v in order:
            for w in sorted(adj[v], key=order.index):
                if frozenset((v, w)) not in done:
                    done.add(frozenset((v, w)))
                    out.append(f"  run {name[v]} to {name[w]}")
        if rid in notes_in:
            out += text_block("description", " ".join(notes_in[rid]["description"]))
            out += text_block("dm_notes", " ".join(notes_in[rid]["dm_notes"]))
        for f in feats_in.get(rid, []):
            out += feature_lines(f)
            stats["feature"] += 1
        for x in exits_in.get(rid, []):
            out += exit_lines(x)
            stats["exit"] += 1
        out += ["}", ""]
        stats["corridor"] += 1

    # two spaces joined by several bare gaps (two caves touching twice) are one
    # connection in the graph; keep the widest gap, so the validator's duplicate
    # warning is about real doubled doors only
    widest: dict = {}
    for c in conns:
        if c["type"] == "open":
            key = (min(c["a"], c["b"]), max(c["a"], c["b"]))
            if key not in widest or c.get("width", 1) > widest[key].get("width", 1):
                widest[key] = c
    conns = [c for c in conns if c["type"] != "open" or widest[(min(c["a"], c["b"]), max(c["a"], c["b"]))] is c]

    door_text = cfg.get("door_text", {})     # e.g. {"arch": "A"}: a door type described by a features-key entry
    for c in conns:
        ra, rb = regions[c["a"]], regions[c["b"]]
        if c.get("frm") is not None and region[c["frm"]] == c["b"]:
            ra, rb = rb, ra                    # one-way: `connects` runs from → to
        out += [f'door at {fmt(c["pos"][0])},{fmt(c["pos"][1])} {{', f"  connects {ident(ra)}, {ident(rb)}",
                f'  type {c["type"]}']
        if c.get("state"):
            out.append(f'  state {c["state"]}')
        if c.get("width", 1) > 1:
            out.append(f'  width {c["width"]}')
        if (k := door_text.get(c["type"])) and k in desc["features_key"]:
            first, _, rest = desc["features_key"][k].partition(". ")
            out += text_block("description", first.rstrip(".") + ".")
            out += text_block("dm_notes", f"Feature {k}. " + rest)
        elif k and "." in k:                     # "traps.Portcullis": legend text, GM side
            out += text_block("dm_notes", text_ref(k))
        out += ["}", ""]
        stats["door_" + c["type"]] += 1

    job.dmap.write_text("\n".join(out) + "\n")
    np.save(job.work / "region.npy", region)
    save_json(job.work / "walls.json", sorted([list(map(list, e)) for e in detected_walls]))
    save_json(job.work / "seg.json", {"labels": {k: list(v) for k, v in labels.items()},
                                      "caves": sorted(k for k, v in cave_label.items() if v)})
    rooms = sorted((r["name"] for r in keep if r["kind"] != "corridor"), key=lambda n: (len(n), n))
    missing = sorted(set(labels) - set(rooms), key=lambda n: (len(n), n))
    print(f"build: {dict(stats)}")
    print(f"  rooms: {rooms}" + (f"\n  labels without a room: {missing}" if missing else ""))
    print(f"  -> {job.dmap}")
