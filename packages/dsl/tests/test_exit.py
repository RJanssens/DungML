"""`exit` — a cross-map transition linking to a map + position elsewhere."""
from __future__ import annotations

from dungml import build_graph, fog_of_war, parse, render, validate


def _map(body: str) -> str:
    return (
        'map "M" { grid { bounds 12 x 9 } renderer "classic-bw" }\n'
        'room "r" { rect 0,0 12 x 9 }\n' + body + "\n"
    )


def test_parses_target_map_and_position():
    m = parse(_map('exit at 3,4 { to "cellar" at 10,2 }'))
    ex = m.exits[0]
    assert ex.position == (3.0, 4.0)
    assert ex.target_map == "cellar"
    assert ex.target_position == (10.0, 2.0)
    assert ex.label is None
    assert ex.secret is False


def test_parses_optional_label_and_notes():
    m = parse(
        _map(
            'exit at 3,4 {\n'
            '  to "cellar" at 10,2\n'
            '  label "To the cellar"\n'
            '  description "A trapdoor in the floor."\n'
            '  dm_notes "Leads to area 7."\n'
            '}'
        )
    )
    ex = m.exits[0]
    assert ex.label is not None and ex.label.text == "To the cellar"
    assert ex.description == "A trapdoor in the floor."
    assert ex.dm_notes == "Leads to area 7."


def test_missing_target_is_a_parse_error():
    import pytest

    from dungml import DmapParseError

    with pytest.raises(DmapParseError):
        parse(_map('exit at 3,4 { label "nowhere" }'))


def test_renders_with_target_data_attributes():
    svg = render(parse(_map('exit at 3,4 { to "cellar" at 10,2 label "Down" }')))
    assert 'class="exit"' in svg
    assert 'data-exit-to="cellar"' in svg
    assert 'data-target-x="10"' in svg
    assert 'data-target-y="2"' in svg
    assert 'data-label="Down"' in svg


def test_out_of_bounds_warns():
    diags = validate(parse(_map('exit at 99,99 { to "cellar" at 1,1 }')))
    assert any(
        d.severity == "warning" and "outside the map bounds" in d.message
        for d in diags
    )


def test_valid_exit_is_clean():
    diags = validate(parse(_map('exit at 3,4 { to "cellar" at 10,2 }')))
    assert not any(d.severity == "error" for d in diags)


def test_exit_is_not_a_graph_node():
    # An exit leaves the map; it must not add nodes/edges to the single-map
    # connectivity graph (only rooms/corridors/doors do).
    g = build_graph(parse(_map('exit at 3,4 { to "cellar" at 10,2 }')))
    assert set(g.nodes) == {"room.r"}
    assert g.edges == []


def test_secret_exit_hidden_in_fog():
    m = parse(_map('exit at 3,4 { to "cellar" at 10,2 secret }'))
    fogged = fog_of_war(m, {"room.r"}, set())
    assert fogged.exits == []
    # A non-secret exit survives fog.
    m2 = parse(_map('exit at 3,4 { to "cellar" at 10,2 }'))
    fogged2 = fog_of_war(m2, {"room.r"}, set())
    assert len(fogged2.exits) == 1


def test_exit_inside_layer():
    m = parse(
        _map(
            'layer "sub" {\n'
            '  exit at 5,5 { to "tower" at 2,2 }\n'
            '}'
        )
    )
    assert m.layers[0].exits[0].target_map == "tower"
