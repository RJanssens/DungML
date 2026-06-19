"""Tests for branching corridors authored with the `node` / `run` form."""
from __future__ import annotations

import re

import pytest

from dungml import build_graph, parse, render, validate
from dungml.errors import DmapParseError
from dungml.model import LineSegment

CROSSROADS = """
map "M" { grid { bounds 40 x 40 } }
corridor "c" {
  width 2
  node hub at 20,20
  node n at 20,8
  node s at 20,32
  node e at 32,20
  node w at 8,20
  run hub to n
  run hub to s
  run hub to e
  run hub to w
}
"""


def _floor_path(svg: str) -> str:
    return re.search(r'class="corridor-floor"[^>]*d="([^"]+)"', svg).group(1)


def test_runs_desugar_to_line_segments() -> None:
    m = parse(CROSSROADS)
    c = m.corridors["c"]
    assert len(c.segments) == 4
    assert all(isinstance(s, LineSegment) for s in c.segments)


def test_named_nodes_are_kept_on_the_model() -> None:
    m = parse(CROSSROADS)
    assert m.corridors["c"].nodes == {
        "hub": (20, 20),
        "n": (20, 8),
        "s": (20, 32),
        "e": (32, 20),
        "w": (8, 20),
    }


def test_run_to_unknown_node_is_an_error() -> None:
    with pytest.raises(DmapParseError, match="unknown node 'ghost'"):
        parse(
            """
            map "M" { grid { bounds 40 x 40 } }
            corridor "c" { node a at 1,1 run a to ghost }
            """
        )


def test_crossing_renders_as_two_through_subpaths() -> None:
    # Four runs sharing `hub` chain into two straight pass-throughs that
    # cross at the hub, each drawn as its own M…-started sub-path.
    d = _floor_path(render(parse(CROSSROADS)))
    assert d.count("M") == 2


def test_branching_corridor_does_not_warn_against_itself() -> None:
    # Junction slivers within one corridor must not trip the overlap warning.
    warns = [d for d in validate(parse(CROSSROADS)) if "overlap" in d.message]
    assert warns == []


def test_branching_corridor_is_one_connected_graph_node() -> None:
    # The whole branching shape is a single node; arms are not separate nodes
    # and need no internal doors to be mutually reachable.
    g = build_graph(parse(CROSSROADS))
    assert "corridor.c" in g.nodes
    assert sum(n.startswith("corridor.") for n in g.nodes) == 1


def test_l_bend_from_two_runs_is_one_contiguous_subpath() -> None:
    # An L authored as two runs meeting at a corner chains into a single
    # sub-path, so the corner keeps its rounded wall join (no butt-cap gap).
    src = """
    map "M" { grid { bounds 40 x 40 } }
    corridor "c" {
      node a at 4,4
      node corner at 4,20
      node b at 20,20
      run a to corner
      run corner to b
    }
    """
    d = _floor_path(render(parse(src)))
    assert d.count("M") == 1


def test_segment_and_run_forms_can_be_mixed() -> None:
    src = """
    map "M" { grid { bounds 40 x 40 } }
    corridor "c" {
      segment line from 2,2 to 2,10
      node a at 2,10
      node b at 12,10
      run a to b
    }
    """
    c = parse(src).corridors["c"]
    assert len(c.segments) == 2
