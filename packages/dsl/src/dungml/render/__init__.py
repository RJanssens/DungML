"""Renderer interface and registry.

A renderer takes a parsed `DungeonMap` and returns a string (SVG, in
practice). Renderers register themselves under a short name; the CLI
and downstream callers look them up by that name.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, ClassVar

from ..model import DungeonMap


class Renderer(ABC):
    """Abstract base for a map renderer.

    Subclasses set the class attribute `name` (used for registration
    and as the value of the `renderer` field in `.dmap`) and implement
    `render`.
    """

    name: ClassVar[str]

    @abstractmethod
    def render(self, dmap: DungeonMap) -> str:
        """Render `dmap` and return the output as text (SVG)."""


_RENDERERS: dict[str, type[Renderer]] = {}


def register(name: str) -> Callable[[type[Renderer]], type[Renderer]]:
    """Decorator that registers a renderer subclass under `name`."""

    def deco(cls: type[Renderer]) -> type[Renderer]:
        cls.name = name
        _RENDERERS[name] = cls
        return cls

    return deco


def get_renderer(name: str) -> type[Renderer]:
    try:
        return _RENDERERS[name]
    except KeyError as exc:
        known = ", ".join(sorted(_RENDERERS)) or "(none registered)"
        raise KeyError(f"unknown renderer {name!r}; known: {known}") from exc


def list_renderers() -> list[str]:
    return sorted(_RENDERERS)


# Importing the built-in renderers registers them as a side effect.
from . import classic_bw  # noqa: E402, F401
from . import oldschool_blue  # noqa: E402, F401
