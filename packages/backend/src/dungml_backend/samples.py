"""Bundled sample maps that can be imported into a user's account.

At module import we locate the project's `samples/` directory by walking
up from this file and load every `.dmap` file we find. The resulting
list is exposed as a module-level constant the `import-samples` route
returns to clients.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SampleMap:
    name: str
    source: str


def _find_samples_dir() -> Path | None:
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        candidate = parent / "samples"
        if candidate.is_dir() and any(candidate.glob("*.dmap")):
            return candidate
    return None


# Title case the slug-ish filename for display.
_NICE_NAMES = {
    "quickstart": "Quickstart (start here)",
    "cottage": "Miller's Cottage",
    "crypt": "Crypt of Saint Vellis",
    "sunken_library": "The Sunken Library of Cael Voren",
    "black_hare_inn": "The Black Hare Inn",
    "goblin_warren": "Goblin Warren of the Broken Tooth",
    "overland": "Bramblefen Crossing (overland)",
    "river_crossing": "Bridgewater Ford (river + bridge)",
    "warlock_firetop": "The Warlock of Firetop Mountain",
    "maze": "Lich-Lord's Labyrinth (maze)",
}


def _nice_name(slug: str) -> str:
    if slug in _NICE_NAMES:
        return _NICE_NAMES[slug]
    return slug.replace("_", " ").replace("-", " ").title()


_SCENARIO_RX = re.compile(r'^\s*scenario\s+"', re.MULTILINE)


def _load() -> list[SampleMap]:
    d = _find_samples_dir()
    if d is None:
        return []
    out: list[SampleMap] = []
    for path in sorted(d.glob("*.dmap")):
        text = path.read_text(encoding="utf-8")
        # Skip include-only files (feature-def libraries with no top-level
        # `map "..."` block); they're meant to be `include`d by other maps.
        if 'map "' not in text:
            continue
        # Skip scenario files (they bundle other maps and need the
        # scenario renderer, not the map render path the backend serves).
        if _SCENARIO_RX.search(text):
            continue
        out.append(SampleMap(name=_nice_name(path.stem), source=text))
    return out


SAMPLE_MAPS: list[SampleMap] = _load()
EXAMPLE_PROJECT_NAME = "Example: dungml samples"
