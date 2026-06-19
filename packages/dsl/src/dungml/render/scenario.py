"""Scenario renderer — bundles boxed text, DM notes, and a sequence of
rendered map SVGs into a single self-contained HTML document.

The document is meant to print cleanly on standard paper: each map gets
its own `<section class="map">` with a page-break-before rule, so a
browser's "Print to PDF" produces one map per page with prose above.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Optional

from ..errors import DmapParseError
from ..model import DungeonMap, Scenario
from ..parser import parse
from . import get_renderer

_DEFAULT_STYLE = """
:root { color-scheme: light; }
body {
  font-family: Georgia, 'Iowan Old Style', 'Times New Roman', serif;
  font-size: 12pt;
  line-height: 1.45;
  color: #111;
  max-width: 9in;
  margin: 0.5in auto;
  padding: 0 0.5in;
  background: #fdfaf3;
}
h1 { font-size: 24pt; margin-bottom: 0.2em; }
h2 { font-size: 16pt; margin-top: 1.2em; }
h3 { font-size: 13pt; margin: 0 0 0.4em 0; color: #555; text-transform: uppercase; letter-spacing: 0.04em; }
p { margin: 0.4em 0; white-space: pre-wrap; }
.scenario-header { border-bottom: 2px solid #444; margin-bottom: 1em; }
.boxed-text {
  border: 1.5px solid #444;
  background: #f4ecd6;
  padding: 0.8em 1em;
  margin: 0.8em 0;
}
.dm-notes {
  border-left: 3px solid #8a6a32;
  background: #fff8e8;
  padding: 0.6em 1em;
  margin: 0.8em 0;
}
.dm-notes h3 { color: #8a6a32; }
section.map {
  margin-top: 2em;
  padding-top: 1em;
  border-top: 1px dashed #999;
  page-break-before: always;
}
section.map:first-of-type { border-top: none; page-break-before: auto; }
section.map figure { margin: 1em 0; text-align: center; }
section.map svg { max-width: 100%; height: auto; }
.map-missing {
  border: 1.5px dashed #b33;
  padding: 0.8em 1em;
  margin: 1em 0;
  color: #b33;
  font-style: italic;
}
@media print {
  body { max-width: none; margin: 0; padding: 0; background: white; }
  .dm-notes, .boxed-text { break-inside: avoid; }
}
""".strip()


def render_scenario(
    scenario: Scenario,
    *,
    base_dir: Optional[Path] = None,
) -> str:
    """Render a Scenario into a self-contained HTML document.

    `base_dir` is the directory used to resolve each `map "path"` ref
    that isn't already absolute. When None, paths are taken as written.
    """
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8"/>',
        f"<title>{escape(scenario.name)}</title>",
        f"<style>{_DEFAULT_STYLE}</style>",
        "</head>",
        "<body>",
        '<header class="scenario-header">',
        f"<h1>{escape(scenario.name)}</h1>",
        "</header>",
    ]

    if scenario.description:
        parts += [
            '<aside class="boxed-text">',
            "<h3>Read aloud</h3>",
            f"<p>{escape(scenario.description)}</p>",
            "</aside>",
        ]
    if scenario.dm_notes:
        parts += [
            '<aside class="dm-notes">',
            "<h3>DM Notes</h3>",
            f"<p>{escape(scenario.dm_notes)}</p>",
            "</aside>",
        ]

    for ref in scenario.maps:
        parts.append(_render_map_section(ref.path, base_dir))

    parts += ["</body>", "</html>"]
    return "\n".join(parts)


def _render_map_section(path_str: str, base_dir: Optional[Path]) -> str:
    """Load `path_str`, render its map, and return one `<section>` block."""
    resolved = Path(path_str)
    if base_dir is not None and not resolved.is_absolute():
        resolved = base_dir / resolved

    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as e:
        return (
            f'<section class="map"><div class="map-missing">'
            f"Could not read <code>{escape(path_str)}</code>: "
            f"{escape(str(e))}</div></section>"
        )

    try:
        dmap = parse(text, path=str(resolved))
    except DmapParseError as e:
        return (
            f'<section class="map"><div class="map-missing">'
            f"Parse error in <code>{escape(path_str)}</code>: "
            f"{escape(str(e))}</div></section>"
        )

    try:
        renderer = get_renderer(dmap.map.renderer)()
        svg = renderer.render(dmap)
    except Exception as e:  # noqa: BLE001
        return (
            f'<section class="map"><div class="map-missing">'
            f"Render error in <code>{escape(path_str)}</code>: "
            f"{escape(str(e))}</div></section>"
        )

    pieces: list[str] = [
        '<section class="map" '
        f'data-map="{escape(dmap.map.name)}" '
        f'data-source="{escape(path_str)}">',
        f"<h2>{escape(dmap.map.name)}</h2>",
    ]
    if dmap.map.description:
        pieces += [
            '<aside class="boxed-text">',
            "<h3>Read aloud</h3>",
            f"<p>{escape(dmap.map.description)}</p>",
            "</aside>",
        ]
    if dmap.map.dm_notes:
        pieces += [
            '<aside class="dm-notes">',
            "<h3>DM Notes</h3>",
            f"<p>{escape(dmap.map.dm_notes)}</p>",
            "</aside>",
        ]
    pieces += [
        "<figure>",
        svg,
        "</figure>",
        "</section>",
    ]
    return "\n".join(pieces)
