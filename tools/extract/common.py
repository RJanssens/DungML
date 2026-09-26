"""Shared bits of the map-extraction pipeline: the job folder, the style kit,
the grid, and small helpers every step uses.

A *job* is one map page. Its folder holds what a person (or a model) decides
— `job.json`, `labels.json`, `corrections.json`, `key.json` — and a `work/`
subfolder with everything the steps compute from the image. Deleting `work/`
and re-running rebuilds the map from the page plus those decisions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent


def load_json(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise SystemExit(f"missing {path}")
    return json.loads(path.read_text())


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


@dataclass
class Job:
    dir: Path

    @cached_property
    def cfg(self) -> dict:
        return load_json(self.dir / "job.json")

    @property
    def work(self) -> Path:
        w = self.dir / "work"
        w.mkdir(exist_ok=True)
        return w

    @property
    def image(self) -> Path:
        p = Path(self.cfg["image"]).expanduser()
        return p if p.is_absolute() else (self.dir / p).resolve()

    @cached_property
    def style(self) -> dict:
        return Style(self.cfg.get("style", "stonehell")).cfg

    @property
    def style_dir(self) -> Path:
        return Style(self.cfg.get("style", "stonehell")).dir

    @property
    def dmap(self) -> Path:
        return self.dir / f"{self.cfg['name']}.dmap"

    def corrections(self) -> dict:
        return load_json(self.dir / "corrections.json", default={})

    def gray(self) -> np.ndarray:
        return np.asarray(Image.open(self.image).convert("L"), float)

    def grid(self) -> tuple[int, float]:
        g = load_json(self.work / "grid.json")
        return g["cells"], g["pitch"]


@dataclass
class Style:
    """A cartographic style: thresholds and symbol templates that hold for
    every page drawn the same way (one module, one cartographer)."""
    name: str

    @property
    def dir(self) -> Path:
        return HERE / "styles" / self.name

    @cached_property
    def cfg(self) -> dict:
        return load_json(self.dir / "style.json")

    def template(self, name: str) -> np.ndarray:
        return np.asarray(Image.open(self.dir / f"{name}.png").convert("L"), float)


# ---- grid helpers (row i, column j; cell (i, j) spans [jP, (j+1)P) x [iP, (i+1)P)) ----

def nbrs(i: int, j: int, n: int):
    """4-neighbours as (direction, i, j); the first two are right and down,
    so iterating `list(nbrs(...))[:2]` visits every edge once."""
    for d, (ii, jj) in (("r", (i, j + 1)), ("d", (i + 1, j)), ("l", (i, j - 1)), ("u", (i - 1, j))):
        if 0 <= ii < n and 0 <= jj < n:
            yield d, ii, jj


def ekey(a, b):
    return (a, b) if a < b else (b, a)


def fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")
