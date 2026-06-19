"""Scenario top-level block: parser, model, and HTML renderer."""
from __future__ import annotations

from pathlib import Path

import pytest

from dungml import (
    DmapParseError,
    Scenario,
    parse,
    parse_scenario,
    render_scenario,
)


def test_parse_scenario_extracts_prose_and_map_refs() -> None:
    src = """
    scenario "The Affair" {
      description "Read this aloud."
      dm_notes "Keep this private."

      map "samples/crypt.dmap"
      map "samples/sunken_library.dmap"
    }
    """
    s = parse_scenario(src)
    assert isinstance(s, Scenario)
    assert s.name == "The Affair"
    assert s.description == "Read this aloud."
    assert s.dm_notes == "Keep this private."
    assert [m.path for m in s.maps] == [
        "samples/crypt.dmap",
        "samples/sunken_library.dmap",
    ]


def test_parse_rejects_files_with_both_map_and_scenario() -> None:
    src = """
    map "X" { grid { bounds 10 x 10 } }
    scenario "Y" { map "samples/crypt.dmap" }
    """
    with pytest.raises(DmapParseError, match="both"):
        parse(src)


def test_parse_returns_dungeon_map_with_scenario_field() -> None:
    src = """
    scenario "X" {
      description "intro"
      map "samples/crypt.dmap"
    }
    """
    dmap = parse(src)
    assert dmap.scenario is not None
    assert dmap.scenario.name == "X"
    assert dmap.scenario.description == "intro"
    assert dmap.rooms == {}
    assert dmap.corridors == {}


def test_parse_scenario_errors_on_plain_map_file() -> None:
    src = 'map "X" { grid { bounds 10 x 10 } }'
    with pytest.raises(DmapParseError, match="does not contain a `scenario"):
        parse_scenario(src)


def test_only_one_scenario_block_allowed() -> None:
    src = """
    scenario "A" { map "samples/crypt.dmap" }
    scenario "B" { map "samples/sunken_library.dmap" }
    """
    with pytest.raises(DmapParseError, match="more than one"):
        parse(src)


def test_render_scenario_emits_html_with_each_map() -> None:
    # Use the bundled bramblefen sample.
    samples_dir = Path(__file__).resolve().parents[3] / "samples"
    src = (samples_dir / "bramblefen_affair.dmap").read_text(encoding="utf-8")
    scenario = parse_scenario(src)
    html = render_scenario(scenario, base_dir=samples_dir)
    assert "<title>The Affair at Bramblefen</title>" in html
    # Scenario-level prose blocks both rendered.
    assert html.count('class="boxed-text"') >= 1
    assert html.count('class="dm-notes"') >= 1
    # One <section class="map"> per referenced map (three in the sample).
    assert html.count('class="map"') == 3
    # Each referenced map's SVG is inlined.
    assert html.count("<svg") == 3


def test_render_scenario_handles_missing_path_gracefully() -> None:
    s = Scenario(
        name="Broken",
        description="x",
        maps=[],
    )
    # Inject a non-existent path directly to bypass parsing.
    from dungml.model import ScenarioMapRef
    s.maps.append(ScenarioMapRef(path="does/not/exist.dmap"))
    html = render_scenario(s, base_dir=Path("/tmp"))
    assert "map-missing" in html
    assert "does/not/exist.dmap" in html
