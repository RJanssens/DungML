"""Off-grid geometry: round rooms and straight passages at any angle.

The grid pass reads floor cell by cell, which turns a round room into a
staircase of partial cells and a diagonal passage into a zig-zag of them. Some
pages (Stonehell's Hexperiment, the trolls' mine) draw both, so they are found
here first, from the rock/floor boundary itself:

* **circles** — a Hough transform over the boundary pixels; a candidate is kept
  when enough of its circumference *is* boundary with rock outside and floor
  inside, so a pit icon or a round table isn't one.
* **bands** — straight boundary segments off the 0°/90° axes, paired with a
  parallel one a passage-width away with floor between and rock outside.
  Collinear pieces broken by a crossing are one line.

`detect` returns both in grid units; `build` takes their cells out of the grid
pass and emits a `circle` room and a one-segment corridor for each.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage as nd


def boundary(rock: np.ndarray) -> np.ndarray:
    return rock & nd.binary_dilation(~rock, np.ones((3, 3)))


def _sample(mask: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    xi, yi = np.clip(np.round(xs).astype(int), 0, w - 1), np.clip(np.round(ys).astype(int), 0, h - 1)
    return mask[yi, xi]


def find_circles(rock: np.ndarray, P: float, st: dict) -> list[dict]:
    from skimage.transform import hough_circle, hough_circle_peaks
    e = boundary(rock)
    s = 2                                            # Hough at half resolution: memory
    small = nd.binary_dilation(e, np.ones((2, 2)))[::s, ::s]
    radii = np.arange(int(st.get("circle_r_min", 1.4) * P / s), int(st.get("circle_r_max", 4.5) * P / s), 1)
    acc = hough_circle(small, radii)
    _, cxs, cys, rs = hough_circle_peaks(acc, radii, min_xdistance=int(P / s), min_ydistance=int(P / s),
                                         total_num_peaks=60, normalize=True)
    dt = nd.distance_transform_edt(~e)
    th = np.linspace(0, 2 * np.pi, 720, endpoint=False)
    out = []
    for cx, cy, r in zip(cxs * s, cys * s, rs * s):
        cx, cy, r = float(cx), float(cy), float(r)
        # refine: least squares on the boundary pixels near the candidate circle
        ys, xs = np.nonzero(e)
        d = np.hypot(xs - cx, ys - cy)
        near = np.abs(d - r) < 4
        if near.sum() < 20:
            continue
        for _ in range(3):
            px, py = xs[near].astype(float), ys[near].astype(float)
            A = np.c_[2 * px, 2 * py, np.ones_like(px)]
            (a, b, c), *_ = np.linalg.lstsq(A, px ** 2 + py ** 2, rcond=None)
            cx, cy, r = a, b, math.sqrt(max(c + a * a + b * b, 1))
            d = np.hypot(xs - cx, ys - cy)
            near = np.abs(d - r) < 3
        px, py = cx + r * np.cos(th), cy + r * np.sin(th)
        on = dt[np.clip(np.round(py).astype(int), 0, e.shape[0] - 1),
                np.clip(np.round(px).astype(int), 0, e.shape[1] - 1)] <= 2
        outside = _sample(rock, cx + (r + 5) * np.cos(th), cy + (r + 5) * np.sin(th))
        inside = _sample(rock, cx + (r - 5) * np.cos(th), cy + (r - 5) * np.sin(th))
        # a wall: boundary on the circle, rock just outside it, floor just inside
        wall = on & outside & ~inside
        support = float(wall.mean())
        # the disk itself is floor (a filled well or table is rock-grey)
        yy, xx = np.ogrid[: rock.shape[0], : rock.shape[1]]
        disk = (xx - cx) ** 2 + (yy - cy) ** 2 < (r - 4) ** 2
        fl = float((~rock[disk]).mean()) if disk.any() else 0
        # longest run of wall along the circumference: a real round room shows long arcs
        run = best = 0
        runs = []
        k0 = int(np.argmin(wall)) if not wall.all() else 0     # start the scan on a gap
        for w in np.r_[wall[k0:], wall[:k0], [False]]:
            if w:
                run += 1
            elif run:
                runs.append(run)
                run = 0
        best = max(runs, default=len(th) if wall.all() else 0)
        arc = min(best, len(th)) / len(th)
        # the share of the circumference in arcs of 18°+: a round wall cut by doorways
        # is a few long arcs; a staircase of square corners grazing a circle is many
        # short touches
        long_arc = sum(r for r in runs if r >= len(th) / 20) / len(th) if runs else float(wall.all())
        tight = float((wall & (dt[np.clip(np.round(py).astype(int), 0, e.shape[0] - 1),
                                  np.clip(np.round(px).astype(int), 0, e.shape[1] - 1)] <= 1)).mean())
        if st.get("_debug"):
            print(f"cand {cx / P:.2f},{cy / P:.2f} r={r / P:.2f} support={support:.2f} tight={tight:.2f} fl={fl:.2f} arc={arc:.2f} long={long_arc:.2f}")
        # a true arc hugs the circle to a pixel; an octagon's straight sides, or a
        # square room's walls a circle touches from inside, only graze it (pages
        # 98/99/111: circles tight/support ≥ 0.95; octagons ≤ 0.83; page 92's
        # 3×3 room 0.91)
        if support >= st.get("circle_support", 0.4) and tight >= st.get("circle_tight", 0.93) * support \
                and fl >= 0.85 and arc >= 0.1:
            out.append(dict(cx=cx / P, cy=cy / P, r=r / P, support=round(support, 2), arc=round(arc, 2)))
    out.sort(key=lambda c: -c["support"])
    keep = []
    for c in out:
        if all(math.hypot(c["cx"] - k["cx"], c["cy"] - k["cy"]) > 0.6 * max(c["r"], k["r"]) for k in keep):
            keep.append(c)
    for c in keep:          # printed maps draw circles on the quarter-cell
        c["cx"], c["cy"], c["r"] = (round(c[k] * 4) / 4 for k in ("cx", "cy", "r"))
    return keep


def find_bands(rock: np.ndarray, P: float, st: dict, circles: list[dict] = ()) -> list[dict]:
    from skimage.transform import probabilistic_hough_line
    e = boundary(rock)
    for c in circles:        # a round room's wall is not a passage's
        yy, xx = np.ogrid[: rock.shape[0], : rock.shape[1]]
        ring = np.abs(np.hypot(xx - c["cx"] * P, yy - c["cy"] * P) - c["r"] * P) < 4
        e &= ~ring
    segs = probabilistic_hough_line(e, threshold=10, line_length=int(st.get("band_seg_min", 1.0) * P),
                                    line_gap=int(0.15 * P), rng=0,
                                    theta=np.linspace(-np.pi / 2, np.pi / 2, 720, endpoint=False))
    lines = []
    for (x0, y0), (x1, y1) in segs:
        th = math.atan2(y1 - y0, x1 - x0) % math.pi
        deg = math.degrees(th) % 90
        if min(deg, 90 - deg) < st.get("band_axis_tol", 4):
            continue                                  # the grid pass handles 0°/90° walls
        dx, dy = math.cos(th), math.sin(th)
        rho = -dy * x0 + dx * y0
        t = sorted((dx * x0 + dy * y0, dx * x1 + dy * y1))
        lines.append(dict(th=th, rho=rho, t0=t[0], t1=t[1]))
    # merge collinear pieces (a crossing or a door breaks a wall into several)
    lines.sort(key=lambda l: (round(math.degrees(l["th"])), l["rho"]))
    merged: list[dict] = []
    for l in lines:
        for m in merged:
            if abs(_dth(l["th"], m["th"])) < 2.5 and abs(_rho_at(l, m["th"]) - m["rho"]) < 4 \
                    and l["t0"] <= m["t1"] + 1.6 * P and l["t1"] >= m["t0"] - 1.6 * P:
                m["t0"], m["t1"] = min(m["t0"], l["t0"]), max(m["t1"], l["t1"])
                m["n"] += 1
                break
        else:
            merged.append(dict(l, n=1))
    if st.get("_debug"):
        for m in merged:
            print(f"line th={math.degrees(m['th']):.1f} rho={m['rho']:.1f} t={m['t0']:.0f}..{m['t1']:.0f} n={m['n']}")
    wmin, wmax = st.get("band_width", [0.55, 2.6])
    pairs = []
    for a in range(len(merged)):
        for b in range(a + 1, len(merged)):
            la, lb = merged[a], merged[b]
            if abs(_dth(la["th"], lb["th"])) > 3:
                continue
            th = la["th"]
            ra, rb = sorted((la["rho"], _rho_at(lb, th)))
            w = rb - ra
            if not wmin * P <= w <= wmax * P:
                continue
            t0, t1 = max(la["t0"], lb["t0"]), min(la["t1"], lb["t1"])
            if t1 - t0 < st.get("band_len_min", 1.5) * P:
                continue
            ts = np.arange(t0, t1, 2.0)
            dx, dy = math.cos(th), math.sin(th)

            def at(rho):
                return ts * dx - rho * dy, ts * dy + rho * dx
            mid = [~_sample(rock, *at(r)) for r in np.linspace(ra + 3, rb - 3, 5)]
            flo = float(np.mean(mid))
            out_a, out_b = _sample(rock, *at(ra - 4)).mean(), _sample(rock, *at(rb + 4)).mean()
            if flo >= 0.9 and out_a >= 0.6 and out_b >= 0.6:
                pairs.append(dict(th=th, rho=(ra + rb) / 2, w=w, t0=t0, t1=t1, la=a, lb=b))
    pairs.sort(key=lambda p: -(p["t1"] - p["t0"]))
    H, W = rock.shape

    def in_circle(x, y):
        return any(math.hypot(x / P - c["cx"], y / P - c["cy"]) < c["r"] for c in circles)

    def floor_run(x, y, nx, ny, lim):
        # how far floor reaches from (x, y) along (nx, ny), up to lim px
        for s in range(1, int(lim)):
            xx, yy = int(round(x + nx * s)), int(round(y + ny * s))
            if not (0 <= xx < W and 0 <= yy < H) or rock[yy, xx]:
                return s
        return lim

    def track(x, y, dx, dy, w):
        # follow the passage from its seed: re-centre between the walls each step (a
        # printed band wobbles, and may bend a few degrees), until the centre line meets
        # the space it opens into — a circle's rim; or, where it meets a straight wall
        # at a slant so one flank opens before the other, halfway between the two
        # flanks opening, which is where the centre line crosses that wall
        pts, first, step, lim = [(x, y)], None, 2.0, w / 2 + 8
        while True:
            x, y = x + dx * step, y + dy * step
            if not (0 <= x < W and 0 <= y < H):
                return pts, "edge"                       # off the page: an exit stub
            if in_circle(x, y):
                return pts + [(x, y)], "circle"
            if rock[int(y), int(x)]:
                return pts, "dead"
            nx, ny = -dy, dx
            a, b = floor_run(x, y, nx, ny, lim), floor_run(x, y, -nx, -ny, lim)
            fa, fb = a >= lim, b >= lim
            if fa and fb:
                if first is None:
                    return pts, "open"
                return pts[:first + (len(pts) - first) // 2 + 1], "open"
            if fa or fb:
                first = len(pts) if first is None else first
            else:
                s = (a - b) / 2                          # re-centre (both walls in reach)
                x, y = x + nx * s * 0.5, y + ny * s * 0.5
            pts.append((x, y))
            if len(pts) >= 12 and first is None:          # direction from the recent run
                (ax, ay), (bx, by) = pts[-12], pts[-1]
                d = math.hypot(bx - ax, by - ay)
                dx, dy = (bx - ax) / d, (by - ay) / d

    def beyond(x, y, dx, dy, w):
        # a band that opened into a crossing corridor may carry on past its far wall
        # (page 111's long spokes cross the 23–24 hall): the first point ahead where
        # the passage is narrow again, for a fresh trace
        lim, run = w / 2 + 8, 0
        for k in range(1, int(2.5 * P / 2)):
            xx, yy = x + dx * 2 * k, y + dy * 2 * k
            if not (0 <= xx < W and 0 <= yy < H) or rock[int(yy), int(xx)] or in_circle(xx, yy):
                return None
            a, b = floor_run(xx, yy, -dy, dx, lim), floor_run(xx, yy, dy, -dx, lim)
            run = run + 1 if a < lim and b < lim else 0
            if run * 2 >= 0.4 * P:
                return xx - dx * 2 * run, yy - dy * 2 * run
        return None

    from skimage.measure import approximate_polygon
    bands = []
    seeds = []
    for p in pairs:
        dx, dy = math.cos(p["th"]), math.sin(p["th"])
        tm = (p["t0"] + p["t1"]) / 2
        seeds.append((tm * dx - p["rho"] * dy, tm * dy + p["rho"] * dx, dx, dy, p["w"], p["th"]))
    while seeds:
        x, y, dx, dy, w, th = seeds.pop(0)
        if any(_near_band(x / P, y / P, b) for b in bands):
            continue                                      # already traced from another seed
        fwd, why1 = track(x, y, dx, dy, w)
        back, why0 = track(x, y, -dx, -dy, w)
        pts = np.array(back[::-1] + fwd[1:])
        if len(pts) < 3:
            continue
        for (ex, ey), (ux, uy), why in ((fwd[-1], (dx, dy), why1), (back[-1], (-dx, -dy), why0)):
            if why == "open" and (nxt := beyond(ex, ey, ux, uy, w)):
                seeds.append((*nxt, ux, uy, w, th))
        pl = approximate_polygon(pts, st.get("band_simplify", 0.12) * P)
        bands.append(dict(points=[[float(px / P), float(py / P)] for px, py in pl],
                          width=round(w / P, 2), ends=[why0, why1],
                          angle=round(math.degrees(th), 1)))
    return bands


def _near_band(x, y, b, tol=0.5):
    pts = b["points"]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy or 1e-9
        t = max(0, min(1, ((x - ax) * vx + (y - ay) * vy) / L2))
        if math.hypot(x - ax - t * vx, y - ay - t * vy) < tol * max(b["width"], 1):
            return True
    return False


def _dth(a, b):
    d = (a - b) % math.pi
    return math.degrees(d if d < math.pi / 2 else d - math.pi)


def _rho_at(l, th):
    # the offset of line l's midpoint measured across direction th
    tm = (l["t0"] + l["t1"]) / 2
    x = tm * math.cos(l["th"]) - l["rho"] * math.sin(l["th"])
    y = tm * math.sin(l["th"]) + l["rho"] * math.cos(l["th"])
    return -math.sin(th) * x + math.cos(th) * y


def _ncc(a, b):
    a, b = a - a.mean(), b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d else 0.0


def door_at(g: np.ndarray, temps: dict, x: float, y: float, dx: float, dy: float, P: float, st: dict,
            reach: tuple = (-0.7, 0.4)):
    """The best door-like template across a passage running (dx, dy) near (x, y) px
    — for doors drawn at a slant (a spoke's end) or off the lattice (a round
    room's rim), which the lattice scan in `symbols` can't see. The window is
    sampled in the passage's frame, so the upright templates apply at any angle.
    Returns (template, score, (x, y)) or None."""
    A, L = st["template_half"]["across"], st["template_half"]["along"]
    u, v = np.arange(-A, A + 1, dtype=float), np.arange(-L, L + 1, dtype=float)
    best = None
    for s in np.arange(reach[0] * P, reach[1] * P, 1.0):
        cx, cy = x + dx * s, y + dy * s
        X = cx + u[None, :] * dx - v[:, None] * dy
        Y = cy + u[None, :] * dy + v[:, None] * dx
        w = nd.map_coordinates(g, [Y, X], order=1, mode="nearest")
        if w.std() < st.get("mid_cell_min_std", 20):
            continue
        for name, tm in temps.items():
            sc = _ncc(w, tm)
            if best is None or sc > best[1]:
                best = (name, sc, (cx, cy))
    if best and best[1] >= st.get("slant_door_margin", 0.5):
        return best
    return None


def detect(rock: np.ndarray, P: float, st: dict) -> dict:
    circles = find_circles(rock, P, st)
    return {"circles": circles, "bands": find_bands(rock, P, st, circles)}


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    from PIL import Image, ImageDraw

    sys.path.insert(0, str(Path(__file__).parent))
    from common import Job
    job = Job(Path(sys.argv[1]))
    n, P = job.grid()
    rock = np.load(job.work / "rock.npy")
    v = detect(rock, P, dict(job.style, _debug="-v" in sys.argv))
    print(json.dumps(v, indent=1))
    im = Image.open(job.image).convert("RGB")
    d = ImageDraw.Draw(im)
    for c in v["circles"]:
        x, y, r = c["cx"] * P, c["cy"] * P, c["r"] * P
        d.ellipse([x - r, y - r, x + r, y + r], outline=(220, 0, 0), width=3)
    for b in v["bands"]:
        d.line([(x * P, y * P) for x, y in b["points"]], fill=(0, 0, 255), width=max(2, int(b["width"] * P / 3)))
        for x, y in b["points"]:
            d.ellipse([x * P - 4, y * P - 4, x * P + 4, y * P + 4], fill=(255, 140, 0))
    im.save(job.work / "vector_dbg.png")
