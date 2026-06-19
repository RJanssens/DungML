"""`dmap` command-line interface.

Subcommands:
- `dmap render INPUT [-o OUT] [--renderer NAME]` — parse, validate, render to SVG.
- `dmap validate INPUT` — parse and validate, exit non-zero on any error diagnostic.
- `dmap renderers` — list registered renderer names.
- `dmap path INPUT FROM TO [--through-locked]` — shortest route between two nodes.

Use `-` as INPUT (or OUT) to read stdin (or write stdout).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import (
    DmapParseError,
    build_graph,
    is_blocked,
    list_renderers,
    parse,
    parse_scenario,
    render as do_render,
    validate,
)
from .render.scenario import render_scenario


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dmap",
        description="dungml — parse, validate, and render .dmap files.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_render = sub.add_parser("render", help="render a .dmap file to SVG")
    p_render.add_argument("input", help="path to .dmap, or - for stdin")
    p_render.add_argument(
        "-o", "--output", default="-",
        help="output path, or - for stdout (default: stdout)",
    )
    p_render.add_argument(
        "--renderer",
        help="renderer name (defaults to the value in the .dmap file)",
    )
    p_render.add_argument(
        "--strict", action="store_true",
        help="exit non-zero if validation produces any diagnostics",
    )

    p_validate = sub.add_parser("validate", help="parse and validate")
    p_validate.add_argument("input")

    sub.add_parser("renderers", help="list registered renderers")

    p_scen = sub.add_parser(
        "render-scenario",
        help="render a scenario .dmap file (boxed text + DM notes + each map's render) to HTML",
    )
    p_scen.add_argument("input", help="path to a .dmap file with a `scenario` block")
    p_scen.add_argument(
        "-o", "--output", default="-",
        help="output path, or - for stdout (default: stdout)",
    )

    p_path = sub.add_parser(
        "path", help="find the shortest route between two rooms/corridors"
    )
    p_path.add_argument("input", help="path to .dmap, or - for stdin")
    p_path.add_argument("from_node", metavar="FROM", help="e.g. room.antechamber")
    p_path.add_argument("to_node", metavar="TO", help="e.g. room.vault")
    p_path.add_argument(
        "--through-locked", action="store_true",
        help="allow routing through locked/barred doors (default: skip them)",
    )

    args = parser.parse_args(argv)

    if args.cmd == "render":
        return _cmd_render(args)
    if args.cmd == "validate":
        return _cmd_validate(args)
    if args.cmd == "path":
        return _cmd_path(args)
    if args.cmd == "renderers":
        for name in list_renderers():
            print(name)
        return 0
    if args.cmd == "render-scenario":
        return _cmd_render_scenario(args)
    parser.error(f"unknown subcommand {args.cmd!r}")
    return 2  # unreachable; argparse.error raises SystemExit


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _write(path: str, content: str) -> None:
    if path == "-":
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
        return
    Path(path).write_text(content, encoding="utf-8")


def _cmd_render(args: argparse.Namespace) -> int:
    try:
        src = _read(args.input)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        dmap = parse(src, path=args.input if args.input != "-" else None)
    except DmapParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 1
    diags = validate(dmap)
    errors = [d for d in diags if d.severity == "error"]
    for d in diags:
        print(f"{d.severity}: {d.message}", file=sys.stderr)
    if errors or (args.strict and diags):
        return 1
    try:
        svg = do_render(dmap, args.renderer)
    except KeyError as e:
        print(f"render error: {e}", file=sys.stderr)
        return 1
    _write(args.output, svg)
    return 0


def _cmd_render_scenario(args: argparse.Namespace) -> int:
    try:
        src = _read(args.input)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        scenario = parse_scenario(
            src, path=args.input if args.input != "-" else None
        )
    except DmapParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 1
    base_dir = (
        Path(args.input).resolve().parent
        if args.input and args.input != "-"
        else None
    )
    html = render_scenario(scenario, base_dir=base_dir)
    _write(args.output, html)
    return 0


def _cmd_path(args: argparse.Namespace) -> int:
    try:
        src = _read(args.input)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        dmap = parse(src, path=args.input if args.input != "-" else None)
    except DmapParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 1
    g = build_graph(dmap)
    for node in (args.from_node, args.to_node):
        if not g.has_node(node):
            print(f"error: unknown node {node!r}", file=sys.stderr)
            return 1
    passable = None
    if not args.through_locked:
        passable = lambda e: not is_blocked(e.state)
    path = g.find_path(args.from_node, args.to_node, passable=passable)
    if path is None:
        print(f"no route from {args.from_node} to {args.to_node}")
        return 1
    print(" -> ".join(path.nodes))
    print(f"({path.length} door{'s' if path.length != 1 else ''})")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        src = _read(args.input)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        dmap = parse(src, path=args.input if args.input != "-" else None)
    except DmapParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 1
    diags = validate(dmap)
    for d in diags:
        print(f"{d.severity}: {d.message}")
    return 1 if any(d.severity == "error" for d in diags) else 0


if __name__ == "__main__":
    raise SystemExit(main())
