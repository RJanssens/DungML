"""Party-view check: walk a map the way a party would and check what it gets shown.

Starting from an entrance, the party enters a node, sees its exits (the doors
that aren't secret — `play.visible_doors`, exactly what a session's reveal
does), and moves on through any door it can pass. After every step the
players' view is rebuilt with the same functions a live session uses
(`graph.fog_of_war`, `play.render_fogged`, `room_context.room_context`), and
checked for leaks:

  nodes     only discovered rooms/corridors are drawn
  doors     only discovered doors are drawn; no unfound secret door
  features  no secret feature (traps…); none outside a discovered node
  text      no dm_notes, key title or unexplored room name in what the party
            reads (room_context "perceived") or sees (the SVG)

It also reports what exploration can't reach without help: rooms behind
secret doors, locked doors or portcullises, and sealed rooms (a teleport).
Those are expected for most keyed dungeons — the report lists them so a
human can confirm each one is intended.

Usage:
    uv run --with cairosvg python tools/extract/party.py MAP.dmap --start 1 \\
        [--reveal-secret KEY ...] [--out DIR]

`--start` takes a node id, name or label (resolved like the contract routes
do). `--reveal-secret` simulates the GM revealing a found secret door (by door
key, e.g. `7,25.5`), after which exploration continues through it; `--open`
simulates the GM unlocking a locked door or raising a portcullis.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from dungml import build_graph, parse
from dungml.graph import door_key, fog_of_war, is_blocked
from dungml.play import render_fogged, visible_doors
from dungml.room_context import SessionView, node_label, resolve_node, room_context


@dataclass
class Step:
    n: int
    entered: str
    via: str | None
    nodes: set[str]
    doors: set[str]
    problems: list[str] = field(default_factory=list)


def _nodes_of(dmap) -> dict[str, object]:
    out = {f"room.{k}": v for k, v in dmap.rooms.items()}
    out.update({f"corridor.{k}": v for k, v in dmap.corridors.items()})
    return out


def _public_texts(dmap) -> str:
    """Everything authored as read-aloud text. A GM note may repeat part of
    it ("A glyph carved into wall. Touching it teleports…"); that shared part
    is public by authoring, not a leak."""
    out = [dmap.map.description or ""]
    for obj in _nodes_of(dmap).values():
        out.append(getattr(obj, "description", None) or "")
        out += [f.description or "" for f in getattr(obj, "features", []) or []]
    out += [getattr(d, "description", None) or "" for d in dmap.doors]
    return "\n".join(out)


def _secret_texts(dmap) -> list[tuple[str, str]]:
    """Every GM-only string on the map, as (where, text) — the things that
    must never reach the party."""
    out = []
    for nid, obj in _nodes_of(dmap).items():
        if getattr(obj, "dm_notes", None):
            out.append((nid, obj.dm_notes))
        for f in getattr(obj, "features", []) or []:
            if f.dm_notes:
                out.append((f"{nid}:{f.ref}", f.dm_notes))
    for d in dmap.doors:
        if getattr(d, "dm_notes", None):
            out.append((f"door {d.position}", d.dm_notes))
    if dmap.map.dm_notes:
        out.append(("map", dmap.map.dm_notes))
    return out


def _fragments(text: str) -> list[str]:
    """Distinctive pieces of a GM text: whole sentences of 4+ words. Checking
    whole sentences (not words) keeps a shared phrase like 'stone door' from
    counting as a leak."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.split()) >= 4]


def check_step(dmap, graph, step: Step, *, secret_refs: set[str], gm: list[tuple[str, str]],
               public: str, labels: dict[str, str], svg: str) -> None:
    view = fog_of_war(dmap, step.nodes, step.doors)
    shown = set(_nodes_of(view))
    if extra := shown - step.nodes:
        step.problems.append(f"nodes drawn but undiscovered: {sorted(extra)}")

    for d in view.doors:
        key = door_key(d)
        if key not in step.doors:
            kind = "secret door" if str(d.type) in ("secret", "concealed") else "door"
            step.problems.append(f"undiscovered {kind} drawn at {key}")

    for f in view.features:
        step.problems.append(f"top-level feature {f.ref} at {f.position} ignores the fog")
    for x in view.exits:
        step.problems.append(f"top-level exit at {x.position} to {x.target_map!r} ignores the fog")
    for nid, obj in _nodes_of(view).items():
        for x in getattr(obj, "exits", []) or []:
            if getattr(x, "secret", False):
                step.problems.append(f"secret exit at {x.position} to {x.target_map!r} visible in {nid}")
    for nid, obj in _nodes_of(view).items():
        for f in getattr(obj, "features", []) or []:
            if f.ref in secret_refs or getattr(f, "secret", False):
                step.problems.append(f"secret feature {f.ref} visible in {nid}")

    ctx = room_context(dmap, graph, step.entered, SessionView(
        discovered_nodes=frozenset(step.nodes), discovered_doors=frozenset(step.doors),
        party_location=step.entered))
    perceived = json.dumps(ctx.get("perceived", {}), ensure_ascii=False)
    # the SVG's visible text only: <text> content, <title> tooltips
    svg_text = " ".join(re.findall(r"<(?:text|title)[^>]*>([^<]*)<", svg))
    for where, text in gm:
        for frag in _fragments(text):
            if frag in public:
                continue
            if frag in perceived:
                step.problems.append(f"GM text from {where} in room_context.perceived: {frag[:60]!r}")
            if frag in svg_text:
                step.problems.append(f"GM text from {where} in the rendered SVG: {frag[:60]!r}")
    # labels: several rooms can share one ("Cpt" on 18 crypts), so count — a label may
    # be drawn at most as often as discovered rooms carry it
    shown_labels: dict[str, int] = {}
    for nid, lab in labels.items():
        if lab and lab != nid.split(".", 1)[1]:
            shown_labels.setdefault(lab, 0)
            shown_labels[lab] += nid in step.nodes
    for lab, allowed in shown_labels.items():
        drawn = len(re.findall(rf">\s*{re.escape(lab)}\s*<", svg))
        if drawn > allowed:
            hidden = sorted(n for n, l in labels.items() if l == lab and n not in step.nodes)
            step.problems.append(f"label {lab!r} drawn {drawn}x but only {allowed} discovered "
                                 f"(undiscovered: {', '.join(hidden[:4])})")


def explore(dmap, graph, start: str, reveal_secret: set[str], opened: set[str]):
    """Breadth-first party walk. Yields a Step per node entered."""
    nodes: set[str] = set()
    doors: set[str] = set()
    q = deque([(start, None)])
    seen = {start}
    n = 0
    while q:
        node, via = q.popleft()
        nodes.add(node)
        doors |= visible_doors(graph, node)
        # the GM reveals a found secret door when the party is at it, not in advance —
        # revealing up front would draw it floating in unexplored rock
        doors |= {e.key for e in graph.incident_edges(node) if e.key in reveal_secret}
        n += 1
        yield Step(n, node, via, set(nodes), set(doors))
        for e in graph.incident_edges(node):
            other = e.other(node)
            if other in seen or e.key not in doors:
                continue
            if e.one_way and e.a != node:
                continue                      # can't go back through a one-way door
            if is_blocked(e.state) and e.key not in opened:
                continue                      # locked / portcullis: seen, not passed
            seen.add(other)
            q.append((other, e.key))


def filmstrip(svgs: list[tuple[str, str]], out: Path, per_row: int = 6, size: int = 300) -> None:
    import io

    import cairosvg
    from PIL import Image, ImageDraw
    rows = (len(svgs) + per_row - 1) // per_row
    sheet = Image.new("RGB", (per_row * size, rows * (size + 18)), "white")
    d = ImageDraw.Draw(sheet)
    for k, (title, svg) in enumerate(svgs):
        # cairosvg ignores `paint-order`, so a label's white halo would paint
        # over its own text; drop the halo for the preview only
        svg = svg.replace("paint-order:stroke;", "").replace("stroke:#fafafa;", "stroke:none;")
        png = cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
        x, y = (k % per_row) * size, (k // per_row) * (size + 18)
        sheet.paste(Image.open(io.BytesIO(png)).convert("RGB"), (x, y + 18))
        d.text((x + 4, y + 3), title, fill=(0, 0, 0))
    sheet.save(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map", type=Path)
    ap.add_argument("--start", required=True)
    ap.add_argument("--reveal-secret", nargs="*", default=[],
                    help="secret door keys the GM reveals (the party found them)")
    ap.add_argument("--open", nargs="*", default=[],
                    help="door keys the GM opens (locked doors, portcullises)")
    ap.add_argument("--open-all", action="store_true",
                    help="the GM opens every locked door and portcullis the party reaches")
    ap.add_argument("--reveal-all", action="store_true",
                    help="the GM reveals every secret/concealed door when the party reaches it")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)

    dmap = parse(a.map.read_text(), path=a.map)
    graph = build_graph(dmap)
    if a.open_all:
        a.open = list(a.open) + [e.key for e in graph.edges if is_blocked(e.state)]
    if a.reveal_all:
        a.reveal_secret = list(a.reveal_secret) + [e.key for e in graph.edges if e.hidden]
    start = resolve_node(dmap, graph, a.start)
    if start is None:
        print(f"unknown start {a.start!r}", file=sys.stderr)
        return 2
    labels = {nid: node_label(dmap, nid) for nid in graph.nodes}
    secret_refs = {k for k, fd in dmap.feature_defs.items() if getattr(fd, "secret", False)}
    gm = _secret_texts(dmap)
    public = _public_texts(dmap)
    out = a.out or a.map.with_suffix("")
    out.mkdir(parents=True, exist_ok=True)

    steps, frames = [], []
    for st in explore(dmap, graph, start, set(a.reveal_secret), set(a.open)):
        svg = render_fogged(dmap, st.nodes, st.doors, party_location=st.entered)
        check_step(dmap, graph, st, secret_refs=secret_refs, gm=gm, public=public, labels=labels, svg=svg)
        steps.append(st)
        frames.append((f"{st.n}: {labels.get(st.entered) or st.entered}", svg))

    reached = steps[-1].nodes
    unreached = sorted(set(graph.nodes) - reached)
    why = {}
    for nid in unreached:
        edges = graph.incident_edges(nid)
        kinds = sorted({("secret" if e.hidden else e.state if is_blocked(e.state) else "via unreached")
                        for e in edges}) or ["no doors (sealed)"]
        why[nid] = kinds

    problems = [(s.n, s.entered, p) for s in steps for p in s.problems]
    report = {
        "map": str(a.map), "start": start, "steps": len(steps),
        "reached": len(reached), "total_nodes": len(graph.nodes),
        "problems": [{"step": n, "at": e, "problem": p} for n, e, p in problems],
        "unreached": {nid: {"label": labels.get(nid), "because": why[nid]} for nid in unreached},
    }
    (out / "party_report.json").write_text(json.dumps(report, indent=1))
    keep = [frames[i] for i in sorted({0, 1, 2, 4, 8, 16, 32, len(frames) - 1} & set(range(len(frames))))]
    filmstrip(keep, out / "party_filmstrip.png")

    print(f"{a.map.name}: walked {len(steps)} steps from {labels.get(start)}, "
          f"reached {len(reached)}/{len(graph.nodes)} nodes, {len(problems)} problem(s)")
    for n, e, p in problems[:40]:
        print(f"  step {n} ({labels.get(e) or e}): {p}")
    if unreached:
        print("  not reachable by walking (confirm each is intended):")
        for nid in unreached:
            print(f"    {labels.get(nid) or nid}: {', '.join(why[nid])}")
    print(f"  report + filmstrip in {out}/")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
