"""dungml — DSL parser, semantic model, and renderer ABC."""
from __future__ import annotations

from .builtins import BUILTIN_FEATURES
from .errors import Diagnostic, DmapError, DmapParseError, DmapValidationError
from .graph import (
    BLOCKING_STATES,
    BoundaryExit,
    Edge,
    Graph,
    Node,
    Path,
    build_graph,
    door_key,
    fog_of_war,
    is_blocked,
)
from .play import node_centroid, render_fogged, visible_doors
from .model import (
    ArcEdge,
    ArcSegment,
    BoundaryRoom,
    CircleRoom,
    CircleShape,
    Corridor,
    Door,
    DungeonMap,
    Exit,
    FeatureDef,
    FeatureInstance,
    GridConfig,
    Label,
    Layer,
    LineEdge,
    LineSegment,
    MapConfig,
    Outline,
    Overlay,
    PolygonRoom,
    Area,
    PolygonShape,
    RectRoom,
    Marker,
    RectShape,
    Room,
    Scenario,
    ScenarioMapRef,
    SourceSpan,
    TextAnnotation,
    Window,
)
from .parser import (
    feature_def_origins,
    library_source,
    list_libraries,
    parse,
    parse_scenario,
)
from .render import Renderer, get_renderer, list_renderers
from .render.scenario import render_scenario
from .validate import validate


def render(dmap: DungeonMap, renderer_name: str | None = None) -> str:
    """Convenience: render a parsed map to SVG.

    If `renderer_name` is None, uses `dmap.map.renderer`.
    """
    name = renderer_name or dmap.map.renderer
    return get_renderer(name)().render(dmap)


__all__ = [
    "BUILTIN_FEATURES",
    "Diagnostic",
    "DmapError",
    "DmapParseError",
    "DmapValidationError",
    "BLOCKING_STATES",
    "BoundaryExit",
    "Edge",
    "Graph",
    "Node",
    "Path",
    "build_graph",
    "render_fogged",
    "node_centroid",
    "visible_doors",
    "door_key",
    "feature_def_origins",
    "fog_of_war",
    "is_blocked",
    "ArcEdge",
    "ArcSegment",
    "BoundaryRoom",
    "CircleRoom",
    "CircleShape",
    "Corridor",
    "Door",
    "DungeonMap",
    "Exit",
    "FeatureDef",
    "FeatureInstance",
    "GridConfig",
    "Label",
    "Layer",
    "LineEdge",
    "LineSegment",
    "MapConfig",
    "Outline",
    "Overlay",
    "PolygonRoom",
    "PolygonShape",
    "RectRoom",
    "Marker",
    "TextAnnotation",
    "Area",
    "RectShape",
    "Room",
    "Scenario",
    "ScenarioMapRef",
    "SourceSpan",
    "Window",
    "Renderer",
    "get_renderer",
    "library_source",
    "list_libraries",
    "list_renderers",
    "parse",
    "parse_scenario",
    "render",
    "render_scenario",
    "validate",
]
