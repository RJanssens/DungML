"""Parse errors say what was found, what was expected, and suggest a fix."""
from __future__ import annotations

import pytest

from dungml import DmapParseError, parse

HEAD = 'map "t" { grid { bounds 30 x 20 } }\n'


def _err(body: str) -> DmapParseError:
    with pytest.raises(DmapParseError) as ei:
        parse(HEAD + body)
    return ei.value


def test_misspelt_keyword_names_the_word_and_suggests_the_fix() -> None:
    e = _err('room "a" { rect 1,1 5 x 5 labl "x" }')
    assert "'labl'" in e.message
    assert "did you mean 'label'" in e.message
    assert (e.line, e.column) == (2, 27)


def test_expected_tokens_are_listed_readably() -> None:
    e = _err('room "a" { rect 1,1 5 x 5 labl "x" }')
    assert "expected one of" in e.message
    assert "label" in e.message and "}" in e.message
    assert "RBRACE" not in e.message  # terminal names are an implementation detail


def test_misspelt_top_level_keyword() -> None:
    e = _err("dor at 1,1 { }")
    assert "did you mean 'door'" in e.message


def test_unexpected_end_of_input_mentions_an_unclosed_block() -> None:
    e = _err('room "a" { rect 1,1 5 x 5 ')
    assert "end of input" in e.message
    assert "}" in e.message


def test_leading_dot_number_is_accepted() -> None:
    m = parse(HEAD + 'room "a" { rect 1,1 5 x 5 label "x" at .5,-.25 }')
    assert m.rooms["a"].label.position == (0.5, -0.25)
