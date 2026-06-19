"""Include directive — library lookups, local overrides, cycle handling."""
from __future__ import annotations

import textwrap

import pytest

from dungml import (
    DmapParseError,
    feature_def_origins,
    library_source,
    list_libraries,
    parse,
)
from dungml.parser import LOCAL_ORIGIN


def test_bundled_common_dungeon_include():
    src = textwrap.dedent("""
        include "common-dungeon.dmap"

        map "T" { grid { bounds 20 x 20 } }
        room "r" {
          rect 0,0 10 x 10
          feature "obelisk" at 5,5
          feature "runestone" at 8,8
        }
    """)
    m = parse(src)
    assert "obelisk" in m.feature_defs
    assert "runestone" in m.feature_defs
    # Sanity: the room's features reference defined feature_defs.
    refs = {f.ref for f in m.rooms["r"].features}
    assert refs == {"obelisk", "runestone"}


def test_local_feature_def_overrides_include():
    """A local feature_def with the same name as one in the include
    should win — the include only provides defaults."""
    src = textwrap.dedent("""
        include "common-dungeon.dmap"

        map "T" { grid { bounds 20 x 20 } }

        feature_def "obelisk" {
          shape rect 5 x 5
          background "#000000"
        }

        room "r" { rect 0,0 10 x 10 }
    """)
    m = parse(src)
    fd = m.feature_defs["obelisk"]
    # The local override has a rect shape; the bundled one is a square
    # (also rect) but with different dimensions.
    from dungml import RectShape

    assert isinstance(fd.shape, RectShape)
    assert fd.shape.width == 5.0
    assert fd.background == "#000000"


def test_missing_include_raises():
    src = textwrap.dedent("""
        include "no-such-file.dmap"
        map "T" { grid { bounds 10 x 10 } }
    """)
    with pytest.raises(DmapParseError) as exc:
        parse(src)
    assert "include not found" in str(exc.value)


def test_include_relative_to_file_path(tmp_path):
    """An include path should resolve relative to the source file's
    directory before falling back to the library."""
    lib = tmp_path / "lib.dmap"
    lib.write_text(textwrap.dedent("""
        feature_def "local_thing" {
          shape circle radius 0.5
          background "#abcdef"
        }
    """))
    main = tmp_path / "main.dmap"
    main_src = textwrap.dedent("""
        include "lib.dmap"
        map "T" { grid { bounds 5 x 5 } }
    """)
    main.write_text(main_src)
    m = parse(main_src, path=str(main))
    assert "local_thing" in m.feature_defs
    assert m.feature_defs["local_thing"].background == "#abcdef"


def test_include_cycle_is_tolerated(tmp_path):
    """A → B → A shouldn't blow up; the second visit is silently skipped."""
    a = tmp_path / "a.dmap"
    b = tmp_path / "b.dmap"
    a.write_text('include "b.dmap"\nfeature_def "from_a" { shape circle radius 1 }\n')
    b.write_text('include "a.dmap"\nfeature_def "from_b" { shape circle radius 2 }\n')
    main_src = textwrap.dedent("""
        include "a.dmap"
        map "T" { grid { bounds 5 x 5 } }
    """)
    main = tmp_path / "main.dmap"
    main.write_text(main_src)
    m = parse(main_src, path=str(main))
    assert "from_a" in m.feature_defs
    assert "from_b" in m.feature_defs


def test_included_file_cannot_have_map_block(tmp_path):
    bad = tmp_path / "bad.dmap"
    bad.write_text('map "X" { grid { bounds 5 x 5 } }')
    main_src = textwrap.dedent("""
        include "bad.dmap"
        map "T" { grid { bounds 5 x 5 } }
    """)
    main = tmp_path / "main.dmap"
    main.write_text(main_src)
    with pytest.raises(DmapParseError) as exc:
        parse(main_src, path=str(main))
    assert "must not contain a `map" in str(exc.value)


def test_include_sources_resolves_in_memory():
    """An include is satisfied from `include_sources` without touching the
    filesystem — this is how the backend serves a project's own core.dmap."""
    src = textwrap.dedent("""
        include "core.dmap"
        map "T" { grid { bounds 10 x 10 } }
        room "r" { rect 0,0 5 x 5 }
    """)
    sources = {
        "core.dmap": 'feature_def "project_only" { shape circle radius 0.7 }'
    }
    m = parse(src, include_sources=sources)
    assert "project_only" in m.feature_defs
    # The bundled core's `pillar` must NOT leak in — the project copy wins
    # outright (no filesystem fallback for a name present in the map).
    assert "pillar" not in m.feature_defs


def test_include_sources_wins_over_bundled():
    """When a name exists both in include_sources and the bundled library,
    the in-memory copy takes precedence."""
    src = textwrap.dedent("""
        include "common-dungeon.dmap"
        map "T" { grid { bounds 10 x 10 } }
    """)
    sources = {
        "common-dungeon.dmap": (
            'feature_def "obelisk" { shape circle radius 9 }'
        )
    }
    m = parse(src, include_sources=sources)
    from dungml import CircleShape

    fd = m.feature_defs["obelisk"]
    assert isinstance(fd.shape, CircleShape)
    assert fd.shape.radius == 9.0


def test_include_sources_falls_back_to_filesystem():
    """Names absent from include_sources still resolve against the bundled
    library, so a project's core.dmap doesn't break other includes."""
    src = textwrap.dedent("""
        include "common-dungeon.dmap"
        map "T" { grid { bounds 10 x 10 } }
    """)
    m = parse(src, include_sources={"core.dmap": "# unused here"})
    assert "obelisk" in m.feature_defs


def test_library_source_reads_bundled_core():
    text = library_source("core.dmap")
    assert text is not None
    assert "core.dmap" in text
    assert library_source("does-not-exist.dmap") is None


def test_feature_def_origins_attributes_by_file():
    src = textwrap.dedent("""
        include "core.dmap"
        include "outdoor.dmap"
        map "M" { grid { bounds 10 x 10 } }
        feature_def "homebrew" { shape circle radius 0.3 }
    """)
    o = feature_def_origins(src)
    assert o["homebrew"] == LOCAL_ORIGIN
    assert o["tree"] == "outdoor.dmap"
    assert o["pillar"] == "core.dmap"


def test_feature_def_origins_in_memory_source_wins():
    # A project copy of core.dmap (via include_sources) is attributed to it,
    # and its def — not the bundled one — is what's reported.
    src = textwrap.dedent("""
        include "core.dmap"
        map "M" { grid { bounds 10 x 10 } }
    """)
    o = feature_def_origins(
        src, include_sources={"core.dmap": 'feature_def "ward" { shape circle radius 1 }'}
    )
    assert o == {"ward": "core.dmap"}


def test_feature_def_origins_empty_on_parse_error():
    assert feature_def_origins("totally not a map {{{") == {}


def test_list_libraries_enumerates_bundled():
    libs = list_libraries()
    assert libs == sorted(libs)  # sorted
    assert {"core.dmap", "outdoor.dmap", "forest.dmap"} <= set(libs)
    assert all(name.endswith(".dmap") for name in libs)


def test_nested_includes(tmp_path):
    """A includes B; B includes C; entities from C surface."""
    c = tmp_path / "c.dmap"
    c.write_text('feature_def "deep" { shape circle radius 0.3 }\n')
    b = tmp_path / "b.dmap"
    b.write_text(
        'include "c.dmap"\n'
        'feature_def "mid" { shape circle radius 0.4 }\n'
    )
    main_src = textwrap.dedent("""
        include "b.dmap"
        map "T" { grid { bounds 5 x 5 } }
    """)
    main = tmp_path / "main.dmap"
    main.write_text(main_src)
    m = parse(main_src, path=str(main))
    assert "deep" in m.feature_defs
    assert "mid" in m.feature_defs
