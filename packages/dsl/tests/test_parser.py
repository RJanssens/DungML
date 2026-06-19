"""Parser tests against the canonical samples and small focused snippets."""
from __future__ import annotations

import pytest

from dungml import (
    ArcEdge,
    ArcSegment,
    BoundaryRoom,
    DmapParseError,
    LineEdge,
    LineSegment,
    PolygonRoom,
    RectRoom,
    parse,
)


# ----- canonical samples -----

def test_parse_crypt(crypt_source: str) -> None:
    m = parse(crypt_source)

    assert m.map.name == "Crypt of Saint Vellis"
    assert m.map.grid.cell_px == 32
    assert m.map.grid.unit_name == "feet"
    assert m.map.grid.unit_per_cell == 5.0
    assert m.map.grid.bounds_w == 60
    assert m.map.grid.bounds_h == 40
    assert m.map.renderer == "classic-bw"
    assert m.map.theme == "dark"

    # custom feature definitions (the built-in `core` prelude is also
    # merged into feature_defs, so check the custom defs are a subset).
    assert {"magic_circle", "sarcophagus"} <= set(m.feature_defs)
    sarc = m.feature_defs["sarcophagus"]
    assert len(sarc.overlays) == 1
    assert sarc.overlays[0].offset == (0.2, 0.2)
    assert sarc.overlays[0].fill == "#888888"

    # rooms
    assert set(m.rooms) == {"entry_hall", "throne_chamber", "vestry_alcove"}

    entry = m.rooms["entry_hall"]
    assert isinstance(entry.shape, RectRoom)
    assert entry.shape.position == (5, 5)
    assert (entry.shape.width, entry.shape.height) == (10, 8)
    assert entry.label is not None
    assert entry.label.position is None  # centered
    assert any(f.ref == "chest" and f.rotate == 45 for f in entry.features)

    throne = m.rooms["throne_chamber"]
    assert isinstance(throne.shape, PolygonRoom)
    # 8 vertices: hexagon with short vertical jambs at the east and west doors.
    assert len(throne.shape.points) == 8
    assert throne.label is not None
    assert throne.label.position == (26, 9)
    assert throne.label.size == 1.2
    assert throne.label.rotate == -5
    assert "Tarnished gold leaf" in throne.description

    # boundary room with arc
    vestry = m.rooms["vestry_alcove"]
    assert isinstance(vestry.shape, BoundaryRoom)
    assert vestry.shape.start == (40, 20)
    assert any(isinstance(e, ArcEdge) and e.via == (52, 24) for e in vestry.shape.edges)
    assert sum(isinstance(e, LineEdge) for e in vestry.shape.edges) == 3

    # corridors
    assert set(m.corridors) == {"main_hall", "curved_passage"}
    cp = m.corridors["curved_passage"]
    assert cp.width == 1.5
    assert isinstance(cp.segments[0], LineSegment)
    assert isinstance(cp.segments[1], ArcSegment)
    assert cp.segments[1].sweep == "ccw"

    # doors
    assert len(m.doors) == 4
    locked = [d for d in m.doors if d.state == "locked"]
    assert locked and locked[0].type == "iron"

    # layers
    assert len(m.layers) == 1
    secrets = m.layers[0]
    assert secrets.name == "secrets"
    assert secrets.hidden is True
    assert any(f.ref == "trap" for f in secrets.features)


def test_parse_cottage(cottage_source: str) -> None:
    m = parse(cottage_source)

    assert m.map.name == "Miller's Cottage"
    assert m.map.renderer == "floorplan"
    assert set(m.rooms) == {"kitchen", "parlor", "bedroom"}

    # Furniture features
    refs = [f.ref for f in m.rooms["kitchen"].features]
    assert "hearth" in refs and "stove" in refs and "table" in refs

    # Arches between interior rooms; front door single-side
    arches = [d for d in m.doors if d.type == "arch"]
    assert len(arches) == 2
    front = [d for d in m.doors if d.type == "wooden"]
    assert front and front[0].connects == ["room.parlor"]

    # Windows
    assert len(m.windows) == 3
    by_room = {w.in_ref: w.width for w in m.windows}
    assert by_room["room.parlor"] == 1.5


# ----- focused parser behaviour -----

def test_default_label_is_centered() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "r" {
      rect 1,1 5 x 5
      label "Hi"
    }
    """
    m = parse(src)
    assert m.rooms["r"].label.text == "Hi"
    assert m.rooms["r"].label.position is None


def test_label_with_explicit_position() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "r" {
      rect 1,1 5 x 5
      label "Hi" at 3,3 size 0.8 rotate 12
    }
    """
    m = parse(src)
    lab = m.rooms["r"].label
    assert lab.position == (3, 3)
    assert lab.size == 0.8
    assert lab.rotate == 12


def test_triple_quoted_description_preserves_internal_newlines() -> None:
    src = '''
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "r" {
      rect 1,1 5 x 5
      description """line one
      line two"""
    }
    '''
    m = parse(src)
    assert "line one" in m.rooms["r"].description
    assert "line two" in m.rooms["r"].description


def test_negative_rotation_parses() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "r" {
      rect 1,1 5 x 5
      feature chest at 3,3 rotate -45 scale 1.5
    }
    """
    m = parse(src)
    f = m.rooms["r"].features[0]
    assert f.rotate == -45
    assert f.scale == 1.5


def test_custom_and_builtin_features_in_one_room() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    feature_def "ward" { shape circle radius 0.8 background "#000" }
    room "r" {
      rect 1,1 8 x 8
      feature pillar at 3,3
      feature "ward" at 5,5 scale 2
    }
    """
    m = parse(src)
    refs = [f.ref for f in m.rooms["r"].features]
    assert refs == ["pillar", "ward"]


def test_arc_segment_in_corridor_with_sweep() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 60 x 60 } renderer "x" }
    corridor "c" {
      width 2
      segment arc center 10,10 radius 5 from-angle 0 to-angle 90 sweep cw
    }
    """
    m = parse(src)
    seg = m.corridors["c"].segments[0]
    assert isinstance(seg, ArcSegment)
    assert seg.sweep == "cw"
    assert seg.radius == 5


def test_boundary_with_only_lines_is_valid_shape() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 30 x 30 } renderer "x" }
    room "r" {
      boundary {
        start 5,5
        line to 10,5
        line to 10,10
        line to 5,5
      }
    }
    """
    m = parse(src)
    shape = m.rooms["r"].shape
    assert isinstance(shape, BoundaryRoom)
    assert shape.start == (5, 5)
    assert len(shape.edges) == 3


def test_door_can_connect_two_rooms_directly() -> None:
    src = """
    map "M" { grid { cell 32 px bounds 30 x 30 } renderer "x" }
    room "a" { rect 1,1 5 x 5 }
    room "b" { rect 7,1 5 x 5 }
    door at 6,3 { connects room.a, room.b  type arch }
    """
    m = parse(src)
    assert m.doors[0].connects == ["room.a", "room.b"]
    assert m.doors[0].type == "arch"


def test_room_grid_optional_color() -> None:
    src = '''
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "with_color" { rect 1,1 8 x 8 grid 1 "#cc00cc" }
    room "default" { rect 10,1 6 x 6 grid 2 }
    '''
    m = parse(src)
    assert m.rooms["with_color"].grid == 1
    assert m.rooms["with_color"].grid_color == "#cc00cc"
    assert m.rooms["default"].grid == 2
    assert m.rooms["default"].grid_color is None


def test_line_style_organic_on_room_and_corridor() -> None:
    src = '''
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    room "wild" {
      polygon (1,1) (5,2) (6,6) (2,5)
      line_style organic
    }
    room "default_solid" {
      rect 7,1 4 x 4
    }
    corridor "trail" {
      segment line from 5,3 to 7,3
      line_style organic
    }
    '''
    m = parse(src)
    assert m.rooms["wild"].line_style == "organic"
    assert m.rooms["default_solid"].line_style is None
    assert m.corridors["trail"].line_style == "organic"


def test_background_on_map_room_and_corridor() -> None:
    src = '''
    map "M" {
      grid { cell 32 px bounds 20 x 20 }
      renderer "classic-bw"
      background "#1a1a1a"
    }
    room "pool" {
      rect 1,1 5 x 5
      background "water"
    }
    corridor "path" {
      segment line from 7,3 to 12,3
      background "dirt"
    }
    '''
    m = parse(src)
    assert m.map.background == "#1a1a1a"
    assert m.rooms["pool"].background == "water"
    assert m.corridors["path"].background == "dirt"


def test_corridor_optional_display_name() -> None:
    src = '''
    map "M" { grid { cell 32 px bounds 20 x 20 } renderer "x" }
    corridor "c_slug" "Pretty Walk" {
      segment line from 1,1 to 5,5
    }
    corridor "no_pretty" {
      segment line from 6,6 to 8,8
    }
    '''
    m = parse(src)
    assert m.corridors["c_slug"].display_name == "Pretty Walk"
    assert m.corridors["no_pretty"].display_name is None


def test_map_level_intro_and_dm_notes() -> None:
    src = '''
    map "Citadel" {
      grid { cell 32 px bounds 20 x 20 }
      renderer "classic-bw"
      description """The bell tolls as you cross the threshold."""
      dm_notes "Bell triggers a wandering-monster check."
    }
    room "a" { rect 1,1 5 x 5 }
    '''
    m = parse(src)
    assert "bell tolls" in (m.map.description or "").lower()
    assert "wandering-monster" in (m.map.dm_notes or "")


def test_dm_notes_on_corridor_door_and_feature() -> None:
    src = '''
    map "M" { grid { cell 32 px bounds 30 x 30 } renderer "x" }
    room "a" {
      rect 1,1 5 x 5
      feature chest at 3,3 {
        description "iron-banded"
        dm_notes "false bottom hides a key"
      }
    }
    room "b" { rect 8,1 5 x 5 }
    corridor "c1" {
      width 1.5
      segment line from 6,3 to 8,3
      description "a damp passage"
      dm_notes """floor tile at 7,3 is a pressure plate"""
    }
    door at 6,3 {
      connects room.a, room.b
      type iron
      state locked
      description "iron-bound door"
      dm_notes "trapped: poison needle on the handle"
    }
    '''
    m = parse(src)

    chest = m.rooms["a"].features[0]
    assert chest.description == "iron-banded"
    assert chest.dm_notes == "false bottom hides a key"

    cor = m.corridors["c1"]
    assert cor.description == "a damp passage"
    assert "pressure plate" in (cor.dm_notes or "")

    door = m.doors[0]
    assert door.description == "iron-bound door"
    assert "poison needle" in (door.dm_notes or "")


# ----- error paths -----

def test_missing_map_block_raises() -> None:
    with pytest.raises(DmapParseError):
        parse('room "r" { rect 1,1 2 x 2 }')


def test_grammar_error_raises_with_location() -> None:
    bad = """
    map "M" { grid { cell 32 px bounds 10 x 10 } renderer "x" }
    room "r" { rect notanumber,1 5 x 5 }
    """
    with pytest.raises(DmapParseError) as ei:
        parse(bad)
    assert ei.value.line >= 3
