"""Convert a gridded dungeon-map page into a DungML map. See README.md.

    uv run --with pillow --with numpy --with scipy --with scikit-image --with cairosvg \\
        python tools/extract/convert.py STEP JOB_DIR

Steps, in order (`all` runs prep → symbols → describe → build → score → party):

    prep      grid, rock, floor, label boxes + labels_sheet.png
    symbols   door / secret / arch symbols on grid lines
    describe  room key → descriptions.json (needs key.json)
    build     → <name>.dmap (needs labels.json)
    score     IoU vs the page, validation, topology vs a reference
    party     party-view walk: fog leaks + what can't be reached
    upload    create/update the map on a dmap-server project (job.json "upload")
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import Job  # noqa: E402


def upload(job: Job) -> None:
    """PUT the map's source onto the project map with the same name, or POST a
    new one. `job.json` → "upload": {"base": url, "project": id, "map": name}.
    Auth: DUNGML_TOKEN (default dev-user, the static dev token)."""
    u = job.cfg["upload"]
    base = u.get("base", "http://127.0.0.1:8000").rstrip("/")
    h = {"Authorization": f"Bearer {os.environ.get('DUNGML_TOKEN', 'dev-user')}",
         "Content-Type": "application/json"}

    def call(method, path, body=None):
        r = urllib.request.Request(base + path, method=method, headers=h,
                                   data=json.dumps(body).encode() if body is not None else None)
        return json.load(urllib.request.urlopen(r))

    src = job.dmap.read_text()
    maps = {m["name"]: m["id"] for m in call("GET", f"/api/projects/{u['project']}/maps")}
    if u["map"] in maps:
        call("PUT", f"/api/maps/{maps[u['map']]}", {"source": src})
        mid, verb = maps[u["map"]], "updated"
    else:
        mid, verb = call("POST", f"/api/projects/{u['project']}/maps", {"name": u["map"], "source": src})["id"], "created"
    v = call("GET", f"/api/maps/{mid}/validate")
    d = v.get("diagnostics", []) if isinstance(v, dict) else v
    print(f"upload: {verb} {u['map']!r} ({mid}); server says {sum(x.get('severity') == 'error' for x in d)} errors, "
          f"{sum(x.get('severity') == 'warning' for x in d)} warnings")


def party(job: Job) -> int:
    import party as p
    cfg = job.cfg.get("party", {})
    args = [str(job.dmap), "--start", str(cfg.get("start", "1")), "--out", str(job.work / "party")]
    if cfg.get("reveal_secret"):
        args += ["--reveal-secret", *cfg["reveal_secret"]]
    if cfg.get("open"):
        args += ["--open", *cfg["open"]]
    return p.main(args)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    step, jd = argv
    job = Job(Path(jd).expanduser().resolve())
    import build
    import describe
    import prep
    import score
    import symbols
    steps = {"prep": prep.main, "symbols": symbols.main, "describe": describe.main, "build": build.main,
             "score": score.main, "party": party, "upload": upload}
    if step == "all":
        order = ["prep", "symbols"]
        if (job.dir / "key.json").exists():
            order.append("describe")
        if not (job.dir / "labels.json").exists():
            prep.main(job)
            symbols.main(job)
            print("\nnext: read work/labels_sheet.png and write labels.json, then run `all` again")
            return 1
        order += ["build", "score", "party"]
        rc = 0
        for s in order:
            r = steps[s](job)
            if s == "party":
                rc = r            # party exits 1 when it finds a fog leak
        return rc
    if step not in steps:
        print(__doc__)
        return 2
    rc = steps[step](job)
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
