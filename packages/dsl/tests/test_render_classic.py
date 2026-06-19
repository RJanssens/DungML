"""classic-bw renderer behaviour."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from dungml import parse, render
from dungml.render import get_renderer, list_renderers
from dungml.render.classic_bw import ClassicBW

SVG_NS = "{http://www.w3.org/2000/svg}"


def _parse_svg(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def _findall_class(root: ET.Element, cls: str) -> list[ET.Element]:
    return [e for e in root.iter() if e.get("class") == cls]


def test_classic_bw_registered():
    assert "classic-bw" in list_renderers()
    assert get_renderer("classic-bw") is ClassicBW


def test_floorplan_alias_registered():
    # The cottage sample uses renderer "floorplan".
    assert "floorplan" in list_renderers()


def test_renders_to_valid_svg(crypt_source):
    svg = render(parse(crypt_source))
    root = _parse_svg(svg)
    assert root.tag == f"{SVG_NS}svg"
    # Crypt has `legend` enabled — viewBox extends by LEGEND_HEIGHT (4.0).
    assert root.get("viewBox") == "0 0 60 44"


def test_includes_room_labels(crypt_source):
    svg = render(parse(crypt_source))
    root = _parse_svg(svg)
    labels = [e.text for e in root.iter(f"{SVG_NS}text")]
    # Labels are prefixed with the room's number in source order.
    assert any("Entry Hall" in (lbl or "") for lbl in labels)
    assert any("Throne Room" in (lbl or "") for lbl in labels)
    assert any("Vestry" in (lbl or "") for lbl in labels)
    # First room in the source is entry_hall → number 1.
    assert "1. Entry Hall" in labels


def test_cottage_renderer_picked_from_map_config(cottage_source):
    # Map declares renderer "floorplan"; render() should pick that automatically.
    svg = render(parse(cottage_source))
    assert "Miller" in svg  # title is included as data-name


def test_walls_are_cut_by_doors(cottage_source):
    """The kitchen-parlor shared wall has an arch door at (10,5).

    After door-cutting, no single wall line should run from y=2 to y=9
    along x=10 (that would mean the door wasn't cut). We expect the wall
    to be split into pieces with a gap centered on y=5.
    """
    svg = render(parse(cottage_source))
    root = _parse_svg(svg)
    # Collect vertical line segments at x=10.
    vertical_at_x10: list[tuple[float, float]] = []
    for line in root.iter(f"{SVG_NS}line"):
        x1 = float(line.get("x1"))
        x2 = float(line.get("x2"))
        if abs(x1 - 10) < 1e-3 and abs(x2 - 10) < 1e-3:
            y1, y2 = sorted((float(line.get("y1")), float(line.get("y2"))))
            vertical_at_x10.append((y1, y2))
    # Combined coverage should be split — there must be a gap between two segments.
    spans = sorted(vertical_at_x10)
    gap_found = any(
        spans[i + 1][0] - spans[i][1] > 0.4  # arch door width is 1.0
        for i in range(len(spans) - 1)
    )
    assert gap_found, f"expected a gap in x=10 walls, got {spans}"


def test_features_get_transform(crypt_source):
    svg = render(parse(crypt_source))
    root = _parse_svg(svg)
    feat_groups = [
        e for e in root.iter(f"{SVG_NS}g")
        if e.get("class") == "feature-instance"
    ]
    refs = {e.get("data-ref") for e in feat_groups}
    # Verify a built-in and a custom feature_def both render.
    assert "pillar" in refs
    assert "magic_circle" in refs
    assert "sarcophagus" in refs
    # Each must have a transform attribute.
    assert all(e.get("transform") for e in feat_groups)


def test_hidden_layer_features_are_skipped(crypt_source):
    """The 'secrets' layer is hidden and contains a trap feature.

    A visible map without hidden layers shouldn't include `data-ref="trap"`.
    """
    svg = render(parse(crypt_source))
    assert 'data-ref="trap"' not in svg


def test_corridor_floor_uses_width(crypt_source):
    svg = render(parse(crypt_source))
    root = _parse_svg(svg)
    floors = [
        e for e in root.iter(f"{SVG_NS}path")
        if e.get("class") == "corridor-floor"
    ]
    assert len(floors) >= 1
    # Widths in the sample are 2, 2, 1.5.
    widths = {e.get("stroke-width") for e in floors}
    assert "2" in widths


def test_y_axis_flips_for_bottom_left_origin():
    src = """
    map "X" {
      grid { cell 10 px bounds 10 x 10 origin bottom-left }
    }
    room "r" { rect 0,0 5 x 5 label "R" }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    # Find the label text element and check its transform Y component.
    text = next(root.iter(f"{SVG_NS}text"))
    transform = text.get("transform", "")
    # In flipped mode, the centroid of (0,0)-(5,5) at (2.5, 2.5) becomes y'=10-2.5=7.5
    assert "translate(2.5,7.5)" in transform


def test_label_align_anchors_inside_bbox_top_left():
    src = """
    map "X" {
      grid { cell 10 px bounds 20 x 20 origin top-left }
    }
    room "r" { rect 4,3 10 x 8 label "R" align top left }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    text = next(root.iter(f"{SVG_NS}text"))
    # bbox is (4,3)-(14,11); inset = 0.5 → anchor at (4.5, 3.5).
    assert "translate(4.5,3.5)" in text.get("transform", "")
    assert text.get("text-anchor") == "start"
    assert text.get("dominant-baseline") == "hanging"


def test_label_align_bottom_right_top_left_origin():
    src = """
    map "X" {
      grid { cell 10 px bounds 20 x 20 origin top-left }
    }
    room "r" { rect 4,3 10 x 8 label "R" align bottom right }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    text = next(root.iter(f"{SVG_NS}text"))
    # bbox is (4,3)-(14,11); inset → anchor at (13.5, 10.5).
    assert "translate(13.5,10.5)" in text.get("transform", "")
    assert text.get("text-anchor") == "end"
    assert text.get("dominant-baseline") == "alphabetic"


def test_label_align_flips_baseline_for_bottom_left_origin():
    src = """
    map "X" {
      grid { cell 10 px bounds 20 x 20 origin bottom-left }
    }
    room "r" { rect 4,3 10 x 8 label "R" align top center }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    text = next(root.iter(f"{SVG_NS}text"))
    # In flip-y, world y for visual top is max_y - inset = 11 - 0.5 = 10.5.
    # SVG y = bounds_h - 10.5 = 20 - 10.5 = 9.5.
    assert "translate(9," in text.get("transform", "") or \
           "translate(9.0," in text.get("transform", "")
    assert "9.5)" in text.get("transform", "")
    # Baseline is swapped under scale(1,-1) so visual "top" stays at the top.
    assert text.get("dominant-baseline") == "alphabetic"
    assert text.get("text-anchor") == "middle"


def test_corridor_display_name_does_not_render_on_map():
    """Header form `corridor "slug" "Display"` populates tooltips only —
    no on-map text element is emitted for the corridor."""
    src = """
    map "X" { grid { cell 10 px bounds 30 x 10 } }
    room "a" { rect 0,2 5 x 5 label "A" }
    room "b" { rect 25,2 5 x 5 label "B" }
    corridor "back_crawl" "Back Crawl" {
      width 1
      segment line from 5,4 to 25,4
    }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    assert 'data-label="Back Crawl"' in svg
    corridor_labels = [
        e for e in root.iter(f"{SVG_NS}text")
        if "corridor-label" in (e.get("class") or "")
    ]
    assert corridor_labels == []


def test_corridor_label_block_renders_on_map():
    """An explicit `label "..."` block inside a corridor draws on-map text."""
    src = """
    map "X" { grid { cell 10 px bounds 30 x 10 } }
    room "a" { rect 0,2 5 x 5 label "A" }
    room "b" { rect 25,2 5 x 5 label "B" }
    corridor "back_crawl" "Back Crawl" {
      width 1
      segment line from 5,4 to 25,4
      label "Back Crawl"
    }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    corridor_labels = [
        e for e in root.iter(f"{SVG_NS}text")
        if "corridor-label" in (e.get("class") or "")
    ]
    assert len(corridor_labels) == 1
    assert corridor_labels[0].text == "Back Crawl"
    transform = corridor_labels[0].get("transform", "")
    assert "translate(15,4)" in transform
    assert "rotate(0)" in transform


def test_corridor_label_align_uses_centerline_bbox():
    src = """
    map "X" { grid { cell 10 px bounds 30 x 20 } }
    room "a" { rect 0,2 5 x 5 label "A" }
    room "b" { rect 25,2 5 x 5 label "B" }
    corridor "c" {
      width 1
      segment line from 5,4 to 25,4
      segment line from 25,4 to 25,15
      label "ROUTE" align top right
    }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    label = next(
        e for e in root.iter(f"{SVG_NS}text")
        if "corridor-label" in (e.get("class") or "")
    )
    assert "translate(24.5,4.5)" in label.get("transform", "")
    assert label.get("text-anchor") == "end"
    assert label.get("dominant-baseline") == "hanging"


def test_label_position_overrides_align():
    src = """
    map "X" {
      grid { cell 10 px bounds 20 x 20 origin top-left }
    }
    room "r" { rect 4,3 10 x 8 label "R" at 12,8 align bottom right }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    text = next(root.iter(f"{SVG_NS}text"))
    # `at` wins over `align` — text sits at the absolute coords.
    assert "translate(12,8)" in text.get("transform", "")
    # Falls back to centered default anchors when position is used.
    assert text.get("text-anchor") == "middle"
    assert text.get("dominant-baseline") == "central"


def test_slice_river_emits_bank_fill_and_flow():
    """A river slice draws three stacked paths: outer bank, water-fill
    band, and a dashed centerline flow detail."""
    src = """
    map "X" { grid { cell 10 px bounds 40 x 30 } }
    slice "r" { kind river width 3 segment line from 0,15 to 40,15 }
    """
    svg = render(parse(src))
    assert '<g class="slices">' in svg
    # Three slice paths for a river kind.
    assert svg.count('class="slice slice-bank"') == 1
    assert svg.count('class="slice slice-fill"') == 1
    assert svg.count('class="slice slice-flow"') == 1
    # Bank stroke width = width + 0.32; fill width = width.
    assert 'stroke-width="3.32"' in svg
    # Centerline flow is dashed.
    assert "stroke-dasharray" in svg


def test_slice_ravine_emits_depth_shadow():
    src = """
    map "X" { grid { cell 10 px bounds 40 x 30 } }
    slice "g" { kind ravine width 2 segment line from 0,15 to 40,15 }
    """
    svg = render(parse(src))
    assert 'class="slice slice-bank"' in svg
    assert 'class="slice slice-depth"' in svg
    # Ravine doesn't have flow dashes.
    assert "slice-flow" not in svg


def test_slice_split_emits_thin_crack():
    src = """
    map "X" { grid { cell 10 px bounds 40 x 30 } }
    slice "c" { kind split width 1 segment line from 0,15 to 40,15 }
    """
    svg = render(parse(src))
    # Split renders as shadow + crack — no bank/fill bands.
    assert "slice-bank" not in svg
    assert "slice-fill" not in svg
    assert 'class="slice slice-split"' in svg
    assert 'class="slice slice-split-shadow"' in svg


def test_slice_label_auto_orients_along_segment():
    src = """
    map "X" { grid { cell 10 px bounds 40 x 30 } }
    slice "r" {
      kind river
      width 2
      segment line from 0,15 to 40,15
      label "R. Test"
    }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    labels = [
        e for e in root.iter(f"{SVG_NS}text")
        if "slice-label" in (e.get("class") or "")
    ]
    assert len(labels) == 1
    transform = labels[0].get("transform", "")
    # Auto-anchor sits at the segment midpoint (20, 15), rotated 0° since
    # the segment runs along +x.
    assert "translate(20,15)" in transform
    assert "rotate(0)" in transform


def test_bridge_builtin_renders_with_deck_and_rails():
    src = """
    include "core.dmap"
    map "X" { grid { cell 10 px bounds 40 x 30 } }
    feature bridge at 20,15 rotate 90 scale 2
    """
    svg = render(parse(src))
    # Top-level features are now supported; the bridge has a deck rect
    # plus rails and plank ticks under the feature-instance group.
    assert "bridge-deck" in svg
    # The feature group should carry a transform reflecting the rotate.
    assert "rotate(90)" in svg


def test_map_grid_overlay_emits_lines_at_spacing():
    """`grid_overlay N` at map level draws faint canvas-wide lines at the
    given world-unit spacing."""
    src = """
    map "X" {
      grid { cell 10 px bounds 8 x 6 }
      grid_overlay 1
    }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    grid_groups = [
        e for e in root.iter(f"{SVG_NS}g")
        if e.get("class") == "map-grid"
    ]
    assert len(grid_groups) == 1
    lines = list(grid_groups[0].iter(f"{SVG_NS}line"))
    # bounds 8x6 with spacing 1 → 7 vertical (x=1..7) + 5 horizontal (y=1..5).
    assert len(lines) == 12


def test_map_grid_overlay_default_spacing_and_color():
    """`grid_overlay` with no args defaults to 1-unit spacing, default color
    (no inline stroke attribute on the group)."""
    src = """
    map "X" {
      grid { cell 10 px bounds 4 x 4 }
      grid_overlay
    }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    grid = next(e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "map-grid")
    # No inline stroke when colour omitted; CSS rule handles colour.
    assert grid.get("stroke") is None
    # 4x4 / spacing 1 → 3 vertical + 3 horizontal interior lines.
    assert len(list(grid.iter(f"{SVG_NS}line"))) == 6


def test_map_grid_overlay_color_applied_as_attribute():
    src = """
    map "X" {
      grid { cell 10 px bounds 4 x 4 }
      grid_overlay 2 "#ff0000"
    }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    grid = next(e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "map-grid")
    assert grid.get("stroke") == "#ff0000"


def test_no_grid_overlay_when_not_set():
    """The .map-grid CSS rule is always defined, but no `<g class="map-grid">`
    element should be emitted unless `grid_overlay` is set."""
    src = 'map "X" { grid { cell 10 px bounds 4 x 4 } }'
    svg = render(parse(src))
    assert '<g class="map-grid"' not in svg


def test_window_renders_two_parallel_lines(cottage_source):
    svg = render(parse(cottage_source))
    root = _parse_svg(svg)
    windows = [
        e for e in root.iter(f"{SVG_NS}line")
        if e.get("class") == "window"
    ]
    # Three windows, each rendered as 2 parallel lines.
    assert len(windows) == 6


def test_room_description_emitted_as_data_attribute(crypt_source):
    """Floors carry data-description so the editor preview can show a
    tooltip on hover."""
    svg = render(parse(crypt_source))
    root = _parse_svg(svg)
    floors = [
        e for e in root.iter(f"{SVG_NS}path")
        if e.get("class") == "floor"
    ]
    descriptions = [e.get("data-description") for e in floors]
    # crypt.dmap has descriptions on all three rooms.
    assert all(d for d in descriptions)
    assert any("antechamber" in d for d in descriptions if d)


def test_feature_description_emitted_as_data_attribute(crypt_source):
    svg = render(parse(crypt_source))
    root = _parse_svg(svg)
    feats = [
        e for e in root.iter(f"{SVG_NS}g")
        if e.get("class") == "feature-instance"
    ]
    described = [e for e in feats if e.get("data-description")]
    # Several feature instances in crypt.dmap have descriptions.
    assert len(described) >= 2


def test_undescribed_elements_omit_data_description(cottage_source):
    """Don't emit empty data-description attributes."""
    svg = render(parse(cottage_source))
    # cottage.dmap has only a couple of described elements; most floors
    # and features should have no data-description attribute at all.
    no_desc_count = svg.count(' data-description=""')
    assert no_desc_count == 0


# ----- hatched renderer -----

def test_hatched_renderer_registered():
    assert "hatched" in list_renderers()


def test_hatched_renderer_emits_pattern_def(crypt_source):
    svg = render(parse(crypt_source), "hatched")
    assert '<pattern id="hatch"' in svg
    # Floors should reference the pattern, not the flat color.
    assert "url(#hatch)" in svg
    # Walls / features / labels should still be present and unchanged.
    root = _parse_svg(svg)
    assert root.tag == f"{SVG_NS}svg"
    assert any(
        e.get("class") == "wall" for e in root.iter(f"{SVG_NS}line")
    )


def test_hatched_renderer_via_convenience_helper(cottage_source):
    """`render(map, 'hatched')` round-trips through the registry."""
    svg = render(parse(cottage_source), "hatched")
    assert svg.startswith("<svg")
    assert "url(#hatch)" in svg


# ----- per-room grid overlay -----

def test_room_grid_renders_clipped_lines():
    src = """
    map "T" { grid { bounds 20 x 20 } }
    room "r" {
      rect 2,2 10 x 8
      grid 1
    }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    # The clipPath must exist and be referenced by a room-grid group.
    clip_paths = [e for e in root.iter(f"{SVG_NS}clipPath")]
    assert len(clip_paths) == 1
    assert clip_paths[0].get("id") == "gridclip-r"
    grid_groups = [
        e for e in root.iter(f"{SVG_NS}g")
        if e.get("class") == "room-grid"
    ]
    assert len(grid_groups) == 1
    assert grid_groups[0].get("clip-path") == "url(#gridclip-r)"
    # 10x8 room with spacing 1 → 11 vertical lines (x=2..12) and 9
    # horizontal lines (y=2..10) inside the group.
    lines = list(grid_groups[0].iter(f"{SVG_NS}line"))
    assert len(lines) == 11 + 9


def test_rooms_without_grid_emit_no_grid_overlay(cottage_source):
    svg = render(parse(cottage_source))
    root = _parse_svg(svg)
    grid_groups = [
        e for e in root.iter(f"{SVG_NS}g")
        if e.get("class") == "room-grid"
    ]
    assert grid_groups == []


def test_legend_flag_extends_viewbox_and_emits_legend_group():
    src = """
    map "M" {
      grid { cell 20 px bounds 30 x 20 }
      renderer "classic-bw"
      legend
    }
    room "r" { rect 1,1 10 x 10 }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    # viewBox grew by LEGEND_HEIGHT (4.0) below the map.
    assert root.get("viewBox") == "0 0 30 24"
    legend_groups = [
        e for e in root.iter(f"{SVG_NS}g")
        if e.get("class") == "legend"
    ]
    assert len(legend_groups) == 1
    # Captions should cover every glyph in the legend.
    texts = [t.text for t in legend_groups[0].iter(f"{SVG_NS}text")]
    assert "Archway" in texts
    assert "Portcullis" in texts
    assert "Locked" in texts
    assert "Trapped" in texts
    assert "Secret" in texts
    assert "Window" in texts


def test_legend_off_by_default_keeps_viewbox_at_map_size():
    src = """
    map "M" { grid { cell 20 px bounds 30 x 20 } renderer "classic-bw" }
    room "r" { rect 1,1 5 x 5 }
    """
    svg = render(parse(src))
    root = _parse_svg(svg)
    assert root.get("viewBox") == "0 0 30 20"
    assert not [
        e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "legend"
    ]


def _poly_points(el: ET.Element) -> list[tuple[float, float]]:
    return [
        (float(x), float(y))
        for x, y in (pair.split(",") for pair in el.get("points").split())
    ]


def test_diagonal_corridor_end_squares_to_angled_wall():
    # A 45deg corridor meeting a wall that runs at a shallow angle. The
    # corridor's butt cap diverges from the wall, so an end-mouth patch
    # bridges the wall: its far edge is squared to the wall angle, and the
    # quad straddles the wall (near edge inside the corridor, far edge inside
    # the room) so it buries the gap's jamb caps and the floor-meets-floor
    # seam.
    src = """
    map "M" { grid { cell 20 px bounds 30 x 30 } renderer "classic-bw" }
    room "cave" { polygon (22,6.9) (12.7,8.45) (12.7,20) (22,20) }
    corridor "c" { width 1 node n1 at 13.82,8.27 node n2 at 16,5 run n1 to n2 }
    door at 13.79,8.35 { connects corridor.c, room.cave type wooden }
    """
    root = _parse_svg(render(parse(src)))
    mouths = _findall_class(root, "corridor-mouth")
    assert len(mouths) == 1
    bL, fL, fR, bR = _poly_points(mouths[0])

    ax, ay = 22.0, 6.9
    bx, by = 12.7, 8.45
    wx, wy = bx - ax, by - ay
    wlen = (wx * wx + wy * wy) ** 0.5
    ux, uy = wx / wlen, wy / wlen  # wall unit direction

    # Core guarantee: the far edge is squared to the *wall* angle, not left at
    # the corridor's own 45deg butt cap. (The corridor runs at 45deg; the wall
    # at ~9.5deg — a butt-capped end would be ~80deg off.)
    ex, ey = fR[0] - fL[0], fR[1] - fL[1]
    elen = (ex * ex + ey * ey) ** 0.5
    cross = abs((ex / elen) * uy - (ey / elen) * ux)  # |sin(angle to wall)|
    assert cross < 1e-2, f"far edge not parallel to wall (sin={cross})"

    # Non-degenerate quad.
    area = abs(
        (fL[0] - bL[0]) * (fR[1] - bL[1]) - (fL[1] - bL[1]) * (fR[0] - bL[0])
    )
    assert area > 1e-3


def test_perpendicular_corridor_end_emits_no_mouth():
    # Axis-aligned corridor ending square on an axis-aligned wall: the butt
    # cap already aligns with the wall, so no mouth patch is needed.
    src = """
    map "M" { grid { cell 20 px bounds 30 x 30 } renderer "classic-bw" }
    room "r" { rect 1,2 4 x 3 }
    corridor "c" { width 1 node n1 at 2.5,8 node n2 at 2.5,5 run n1 to n2 }
    door at 2.5,5 { connects corridor.c, room.r type wooden }
    """
    root = _parse_svg(render(parse(src)))
    assert _findall_class(root, "corridor-mouth") == []
