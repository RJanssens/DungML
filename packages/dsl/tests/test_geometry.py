"""Geometry: edge enumeration, shared-edge detection, door cuts."""
from __future__ import annotations

from dungml.geometry import (
    ArcWall,
    LineWall,
    cut_wall,
    overlap_segment,
    project_onto_wall,
    room_walls,
    shared_segments,
)
from dungml.model import (
    BoundaryRoom,
    LineEdge,
    PolygonRoom,
    RectRoom,
    Room,
)


def _rect(name: str, x: float, y: float, w: float, h: float) -> Room:
    return Room(name=name, shape=RectRoom(position=(x, y), width=w, height=h))


# ----- room_walls -----

def test_rect_room_has_four_line_walls():
    r = _rect("k", 0, 0, 4, 3)
    walls = room_walls(r)
    assert len(walls) == 4
    assert all(isinstance(w, LineWall) for w in walls)
    endpoints = {(w.a, w.b) for w in walls}
    assert ((0, 0), (4, 0)) in endpoints
    assert ((4, 0), (4, 3)) in endpoints
    assert ((4, 3), (0, 3)) in endpoints
    assert ((0, 3), (0, 0)) in endpoints


def test_polygon_room_walls_close_the_loop():
    r = Room(name="p", shape=PolygonRoom(points=[(0, 0), (4, 0), (2, 3)]))
    walls = room_walls(r)
    assert len(walls) == 3
    assert walls[-1].b == walls[0].a  # closed


def test_boundary_room_emits_arc_wall_for_arc_edge():
    from dungml.model import ArcEdge

    r = Room(
        name="b",
        shape=BoundaryRoom(
            start=(0, 0),
            edges=[
                LineEdge(end=(8, 0)),
                ArcEdge(end=(8, 8), via=(12, 4)),
                LineEdge(end=(0, 8)),
                LineEdge(end=(0, 0)),
            ],
        ),
    )
    walls = room_walls(r)
    kinds = [type(w).__name__ for w in walls]
    assert kinds == ["LineWall", "ArcWall", "LineWall", "LineWall"]


# ----- overlap_segment -----

def test_overlap_segment_identical():
    seg = overlap_segment(LineWall((0, 0), (4, 0)), LineWall((0, 0), (4, 0)))
    assert seg == ((0, 0), (4, 0))


def test_overlap_segment_partial():
    seg = overlap_segment(LineWall((0, 0), (4, 0)), LineWall((2, 0), (6, 0)))
    assert seg == ((2, 0), (4, 0))


def test_overlap_segment_reversed_direction():
    seg = overlap_segment(LineWall((0, 0), (4, 0)), LineWall((6, 0), (2, 0)))
    assert seg == ((2, 0), (4, 0))


def test_overlap_segment_not_collinear():
    assert overlap_segment(LineWall((0, 0), (4, 0)), LineWall((0, 1), (4, 1))) is None


def test_overlap_segment_single_point_touch_is_none():
    # Endpoint-to-endpoint touch doesn't count as a shared segment.
    assert overlap_segment(LineWall((0, 0), (4, 0)), LineWall((4, 0), (8, 0))) is None


# ----- shared_segments -----

def test_shared_segments_finds_adjacent_room_wall():
    rooms = {
        "kitchen": _rect("kitchen", 0, 0, 4, 3),
        "parlor": _rect("parlor", 4, 0, 4, 3),
    }
    out = shared_segments(rooms)
    assert len(out) == 1
    a, b, seg = out[0]
    assert {a, b} == {"kitchen", "parlor"}
    assert seg == ((4, 0), (4, 3))


def test_shared_segments_no_share_when_diagonal():
    rooms = {
        "a": _rect("a", 0, 0, 4, 3),
        "b": _rect("b", 5, 0, 4, 3),  # gap between
    }
    assert shared_segments(rooms) == []


def test_shared_segments_partial_overlap():
    rooms = {
        "a": _rect("a", 0, 0, 4, 3),
        "b": _rect("b", 4, 1, 4, 3),  # only partial overlap with a's east wall
    }
    out = shared_segments(rooms)
    assert len(out) == 1
    _, _, seg = out[0]
    assert seg == ((4, 1), (4, 3))


# ----- project_onto_wall / cut_wall -----

def test_project_onto_wall_midpoint():
    w = LineWall((0, 0), (4, 0))
    p, t, dist = project_onto_wall((2, 1), w)
    assert p == (2, 0)
    assert t == 0.5
    assert dist == 1.0


def test_project_clamps_to_segment():
    w = LineWall((0, 0), (4, 0))
    _, t, _ = project_onto_wall((6, 0), w)
    assert t == 1.0


def test_cut_wall_full_gap_returns_empty():
    w = LineWall((0, 0), (4, 0))
    assert cut_wall(w, 0, 1) == []


def test_cut_wall_centered_gap_returns_two_pieces():
    w = LineWall((0, 0), (4, 0))
    pieces = cut_wall(w, 0.25, 0.75)
    assert len(pieces) == 2
    assert pieces[0].a == (0, 0)
    assert pieces[0].b == (1, 0)
    assert pieces[1].a == (3, 0)
    assert pieces[1].b == (4, 0)


def test_cut_wall_edge_gap_returns_one_piece():
    w = LineWall((0, 0), (4, 0))
    pieces = cut_wall(w, 0.0, 0.5)
    assert len(pieces) == 1
    assert pieces[0].a == (2, 0)
    assert pieces[0].b == (4, 0)
