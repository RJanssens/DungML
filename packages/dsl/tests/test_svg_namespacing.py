"""Several map SVGs can share one HTML page (the scenario document, the print
page, GM + fog views side by side) without interfering.

Inline SVG ids are document-global and an inline `<style>` applies to the
whole page. So every id a render defines carries a per-render prefix, every
reference points inside the same SVG, and every stylesheet rule is scoped
to the SVG's root class. The prefix is a hash of what is drawn, so identical
renders stay byte-identical (cache-friendly) while different maps or fog
states never collide.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from dungml import parse, render, render_fogged
from dungml.render import list_renderers
from dungml.render.scenario import render_scenario
from dungml.parser import parse_scenario

SVG_NS = "{http://www.w3.org/2000/svg}"

# Exercises every id-bearing construct: textures, organic filter, per-room
# grid clip, cell grid clips, marker image clip.
SRC = """
include "core.dmap"
map "M" {{ grid {{ bounds 30 x 20 }} background "parchment" cell_grid 1 }}
room "a" {{ rect 1,1 8 x 8 label "{label}" background "stone" grid 1 line_style organic }}
room "b" {{ rect 12,1 8 x 8 label "B" }}
corridor "k" {{ segment line from 9,5 to 12,5 }}
door at 9,5 {{ connects room.a, corridor.k }}
door at 12,5 {{ connects corridor.k, room.b type open }}
area "pool" kind water {{ rect 13,2 2 x 2 }}
marker "hero" at 4,4 image "https://example.test/h.png"
"""


def _svg(label: str = "A", renderer: str | None = None) -> str:
    return render(parse(SRC.format(label=label)), renderer)


def _ids_and_refs(svg: str) -> tuple[str, set[str], set[str]]:
    root = ET.fromstring(svg)
    classes = (root.get("class") or "").split()
    ns = next(c for c in classes if c.startswith("dm-"))
    ids = {el.get("id") for el in root.iter() if el.get("id")}
    refs = set(re.findall(r"url\(#([^)]+)\)", svg))
    refs |= {
        v[1:]
        for el in root.iter()
        for k, v in el.attrib.items()
        if k.endswith("href") and v.startswith("#")
    }
    return ns, ids, refs


@pytest.mark.parametrize("renderer", list_renderers())
def test_every_id_is_prefixed_and_every_reference_resolves_locally(renderer: str) -> None:
    ns, ids, refs = _ids_and_refs(_svg(renderer=renderer))
    assert ids, "fixture should define ids"
    assert all(i.startswith(ns + "-") for i in ids), sorted(ids)
    assert refs <= ids, sorted(refs - ids)


def test_fog_stub_ids_are_prefixed_too() -> None:
    src = """
    map "T" { grid { bounds 10 x 10 } }
    corridor "a" { node n1 at 1,5 node n2 at 5,5 run n1 to n2 }
    corridor "b" { node n1 at 5,5 node n2 at 9,5 run n1 to n2 }
    door at 5,5 { connects corridor.a, corridor.b type open }
    """
    svg = render_fogged(parse(src), {"corridor.a"}, {"5,5"})
    ns, ids, refs = _ids_and_refs(svg)
    assert any("fade" in i for i in ids)
    assert all(i.startswith(ns + "-") for i in ids) and refs <= ids


def test_same_render_is_byte_identical() -> None:
    assert _svg() == _svg()


def test_different_maps_get_disjoint_ids() -> None:
    _, ids_a, _ = _ids_and_refs(_svg("A"))
    _, ids_b, _ = _ids_and_refs(_svg("Other"))
    assert ids_a.isdisjoint(ids_b)


def test_gm_and_fog_views_of_one_map_get_disjoint_ids() -> None:
    dmap = parse(SRC.format(label="A"))
    _, gm, _ = _ids_and_refs(render_fogged(dmap, {"room.a"}, set(), full=True))
    _, fog, _ = _ids_and_refs(render_fogged(dmap, {"room.a"}, set()))
    assert gm.isdisjoint(fog)


@pytest.mark.parametrize("renderer", list_renderers())
def test_every_stylesheet_rule_is_scoped_to_the_root(renderer: str) -> None:
    svg = _svg(renderer=renderer)
    ns, _, _ = _ids_and_refs(svg)
    css = "".join(el.text or "" for el in ET.fromstring(svg).iter(f"{SVG_NS}style"))
    selectors = [s.strip() for rule in re.findall(r"([^{}]+)\{", css) for s in rule.split(",")]
    assert selectors
    assert all(s.startswith(f".{ns} ") for s in selectors), selectors


def test_element_classes_are_unchanged() -> None:
    # The web editor matches e.g. `class === "floor"` exactly.
    root = ET.fromstring(_svg())
    floors = [el for el in root.iter(f"{SVG_NS}path") if el.get("data-room")]
    assert floors and all(el.get("class") == "floor" for el in floors)


def test_label_text_mentioning_an_id_is_left_alone() -> None:
    assert ">1. see url(#x)<" in _svg("see url(#x)")


def test_scenario_document_has_no_duplicate_ids(tmp_path: Path) -> None:
    for name, label in (("one", "First"), ("two", "Second")):
        (tmp_path / f"{name}.dmap").write_text(SRC.format(label=label))
    scen = parse_scenario('scenario "S" { map "one.dmap" map "two.dmap" }')
    html = render_scenario(scen, base_dir=tmp_path)
    ids = re.findall(r'\sid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]
