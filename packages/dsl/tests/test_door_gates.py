"""`door … type gates` renders as `-)(-` (two arcs bowing toward centre)."""
from __future__ import annotations

from dungml import parse, render, validate


def _gate_map(dtype: str) -> str:
    return (
        'map "M" { grid { bounds 14 x 8 } renderer "classic-bw" }\n'
        'room "a" { rect 1,1 5 x 5 }\n'
        'room "b" { rect 8,1 5 x 5 }\n'
        'corridor "c" { width 2 segment line from 6,3.5 to 8,3.5 }\n'
        f'door at 6,3.5 {{ connects room.a, corridor.c type {dtype} }}\n'
    )


def test_gates_draws_two_arcs():
    svg = render(parse(_gate_map("gates")))
    # The two gate leaves are stroked arc paths.
    assert svg.count('class="door" fill="none"') == 2
    assert not any(d.severity == "error" for d in validate(parse(_gate_map("gates"))))


def test_gate_singular_alias():
    assert render(parse(_gate_map("gate"))).count('class="door" fill="none"') == 2


def test_wooden_door_has_no_gate_arcs():
    svg = render(parse(_gate_map("wooden")))
    assert 'class="door" fill="none"' not in svg
