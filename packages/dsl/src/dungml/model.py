"""Typed semantic model for a parsed .dmap document."""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

Vec2 = tuple[float, float]


class SourceSpan(BaseModel):
    """Position in the source text, 1-indexed lines and columns."""
    line: int = 0
    column: int = 0
    end_line: int = 0
    end_column: int = 0


# ----- shape primitives (used by feature_def and overlays) -----

class CircleShape(BaseModel):
    kind: Literal["circle"] = "circle"
    radius: float


class RectShape(BaseModel):
    kind: Literal["rect"] = "rect"
    width: float
    height: float


class PolygonShape(BaseModel):
    kind: Literal["polygon"] = "polygon"
    points: list[Vec2]


Shape = Union[CircleShape, RectShape, PolygonShape]


# ----- feature definition -----

class Outline(BaseModel):
    color: Optional[str] = None
    width: Optional[float] = None
    stroke: str = "solid"


class Overlay(BaseModel):
    shape: Shape
    offset: Vec2 = (0.0, 0.0)
    fill: Optional[str] = None


# ----- glyph primitives (low-level line-art draw commands) -----
#
# A `feature_def` may instead carry a `glyph` — an ordered list of raw
# draw commands that map almost 1:1 onto SVG elements. This is the
# vocabulary the built-in features (pillar, stairs, fountain, …) are
# expressed in, and lets users author line-art glyphs rather than the
# filled colored shapes that `shape`/`overlay` produce.
#
# `role` selects the styling class:
#   stroke → class="feature"      (white fill, black outline)
#   fill   → class="feature-fill" (solid black, no stroke)
#   plain  → no class             (style purely via the overrides below)
# `fill`/`stroke`/`stroke_width` are optional per-element overrides
# (a color literal, or the string "none"). `extra_class` appends an
# additional CSS class alongside the role class.

GlyphRole = Literal["stroke", "fill", "plain"]


class GlyphBase(BaseModel):
    role: GlyphRole = "stroke"
    fill: Optional[str] = None
    stroke: Optional[str] = None
    stroke_width: Optional[float] = None
    extra_class: Optional[str] = None


class GlyphCircle(GlyphBase):
    kind: Literal["circle"] = "circle"
    cx: float
    cy: float
    r: float


class GlyphRect(GlyphBase):
    kind: Literal["rect"] = "rect"
    x: float
    y: float
    width: float
    height: float
    rx: Optional[float] = None


class GlyphLine(GlyphBase):
    kind: Literal["line"] = "line"
    x1: float
    y1: float
    x2: float
    y2: float


class GlyphPolygon(GlyphBase):
    kind: Literal["polygon"] = "polygon"
    points: list[Vec2]


class GlyphPolyline(GlyphBase):
    kind: Literal["polyline"] = "polyline"
    points: list[Vec2]


class GlyphPath(GlyphBase):
    kind: Literal["path"] = "path"
    d: str


GlyphElement = Union[
    GlyphCircle, GlyphRect, GlyphLine, GlyphPolygon, GlyphPolyline, GlyphPath
]


class FeatureDef(BaseModel):
    name: str  # slug (id) — the string after `feature_def`
    # A feature is drawn either as a filled `shape` (+ overlays) or as a
    # `glyph` (a list of line-art draw commands). Exactly one is set; the
    # parser enforces this.
    shape: Optional[Shape] = None
    glyph: list[GlyphElement] = Field(default_factory=list)
    background: Optional[str] = None
    outline: Optional[Outline] = None
    overlays: list[Overlay] = Field(default_factory=list)
    description: Optional[str] = None
    display_name: Optional[str] = None  # human-readable label override
    # GM-only: instances of this feature type are stripped from the fogged
    # players' view (e.g. traps). The full GM view still draws them. A feature
    # instance can also opt in individually (see FeatureInstance.secret).
    secret: bool = False
    span: SourceSpan = Field(default_factory=SourceSpan)


# ----- room -----

class Label(BaseModel):
    text: str
    position: Optional[Vec2] = None  # None = centered or aligned via bbox
    # Relative anchor inside the room's bbox; ignored when `position` is set.
    align_v: Optional[Literal["top", "middle", "bottom"]] = None
    align_h: Optional[Literal["left", "center", "right"]] = None
    size: float = 1.0
    rotate: float = 0.0


class FeatureInstance(BaseModel):
    ref: str
    position: Vec2
    rotate: float = 0.0
    # `scale` is the X factor; `scale_y` the Y factor. When `scale_y` is
    # None the scale is uniform (Y = X). Set both via `scale 2:1`.
    scale: float = 1.0
    scale_y: Optional[float] = None
    description: Optional[str] = None
    dm_notes: Optional[str] = None
    # Mark this single instance GM-only (hidden in the fogged players' view)
    # even if its feature type isn't secret by default.
    secret: bool = False
    span: SourceSpan = Field(default_factory=SourceSpan)


class RectRoom(BaseModel):
    kind: Literal["rect"] = "rect"
    position: Vec2
    width: float
    height: float


class PolygonRoom(BaseModel):
    kind: Literal["polygon"] = "polygon"
    points: list[Vec2]


class LineEdge(BaseModel):
    """A straight edge ending at `end`."""
    kind: Literal["line"] = "line"
    end: Vec2


class ArcEdge(BaseModel):
    """A circular-arc edge ending at `end`, passing through `via`.

    The arc's start is the previous edge's endpoint (or `BoundaryRoom.start`
    for the first edge). Three points uniquely determine the arc.
    """
    kind: Literal["arc"] = "arc"
    end: Vec2
    via: Vec2


BoundaryEdge = Union[LineEdge, ArcEdge]


class BoundaryRoom(BaseModel):
    """A room outline with mixed straight + arc edges.

    The boundary is implicitly closed: the renderer joins the final
    edge's endpoint back to `start`.
    """
    kind: Literal["boundary"] = "boundary"
    start: Vec2
    edges: list[BoundaryEdge]


class CircleRoom(BaseModel):
    """A circular room, given by centre and radius. Handled geometrically as
    a finely-sampled polygon so walls / door-cutouts / overlap all just work."""
    kind: Literal["circle"] = "circle"
    center: Vec2
    radius: float


RoomShape = Union[RectRoom, PolygonRoom, BoundaryRoom, CircleRoom]


class Room(BaseModel):
    name: str
    shape: RoomShape
    label: Optional[Label] = None
    description: Optional[str] = None  # boxed text — read to players
    dm_notes: Optional[str] = None  # private notes — traps, secrets, hooks
    features: list[FeatureInstance] = Field(default_factory=list)
    # Exits authored inside this room's block. Like `features`, the nesting is
    # organizational only (the `at x,y` coords are absolute world coords). The
    # parser hoists these into the map-level `exits` list, so downstream
    # (renderer, graph, fog, validation) sees them as ordinary map exits.
    exits: list[Exit] = Field(default_factory=list)
    grid: Optional[float] = None  # spacing (world units) for an in-room grid overlay
    grid_color: Optional[str] = None  # optional CSS color for the grid lines
    # Floor background. CSS color or built-in texture id; overrides the
    # renderer's default room floor when set (e.g. submerged room = "water").
    background: Optional[str] = None
    # Wall edge style — "solid" (clean lines) or "organic" (subtle wiggle
    # via SVG displacement filter — good for natural shapes like forests).
    line_style: Optional[str] = None
    # Optional waviness multiplier for `line_style organic` (1.0 = default).
    line_style_amount: Optional[float] = None
    # When True, this room is excluded from the interior-overlap validation
    # warning — for deliberate stacking (e.g. a ruined building drawn on top
    # of the canyon floor it sits in). Set with the `allow_overlap` keyword.
    allow_overlap: bool = False
    span: SourceSpan = Field(default_factory=SourceSpan)


# ----- corridor -----

class LineSegment(BaseModel):
    kind: Literal["line"] = "line"
    start: Vec2
    end: Vec2


class ArcSegment(BaseModel):
    kind: Literal["arc"] = "arc"
    center: Vec2
    radius: float
    from_angle: float
    to_angle: float
    sweep: str = "ccw"  # "ccw" | "cw"


Segment = Union[LineSegment, ArcSegment]


class Corridor(BaseModel):
    name: str
    display_name: Optional[str] = None  # tooltip / print legend only — not drawn on the map
    width: float = 1.0
    segments: list[Segment] = Field(default_factory=list)
    # Authored junction points (name -> position). Populated when a corridor
    # uses the `node`/`run` form; `run`s are desugared into `segments`, but the
    # named junctions are kept here for tooling (door-attach-by-node, tooltips).
    # Empty for segment-only corridors.
    nodes: dict[str, Vec2] = Field(default_factory=dict)
    label: Optional[Label] = None  # opt-in on-map label, parallels Room.label
    description: Optional[str] = None
    dm_notes: Optional[str] = None
    # Floor fill override (color or built-in texture id). Same semantics as
    # Room.background.
    background: Optional[str] = None
    # Wall edge style — "solid" or "organic". See Room.line_style.
    line_style: Optional[str] = None
    line_style_amount: Optional[float] = None  # waviness multiplier for organic
    # Corner style at bends/junctions: "round" or "straight" (sharp).
    # `None` (default) inherits the map-level `corners` setting, which itself
    # falls back to "round". See MapConfig.default_corners.
    corners: Optional[str] = None
    # Features placed on this corridor (pillars, rubble, portcullis, …). Like
    # Room.features, the `at x,y` coordinates are absolute world coords — the
    # nesting is organizational, not a relative offset.
    features: list[FeatureInstance] = Field(default_factory=list)
    # Exits authored inside this corridor's block — hoisted to the map-level
    # `exits` list by the parser. See Room.exits.
    exits: list[Exit] = Field(default_factory=list)
    span: SourceSpan = Field(default_factory=SourceSpan)


# ----- slice (cross-slice terrain: rivers, ravines, splits) -----

SliceKind = Literal["river", "ravine", "split"]


class Slice(BaseModel):
    """A terrain feature that cuts ACROSS the map — a river, ravine, or
    fault split. Geometry mirrors a corridor (line + arc segments with a
    width), but the rendering treats the band as terrain (water, dirt
    shadow, crack) rather than a passable interior. Bridges go on top as
    regular features; the slice itself doesn't model crossings.
    """
    name: str
    kind: SliceKind = "river"
    width: float = 2.0
    segments: list[Segment] = Field(default_factory=list)
    label: Optional[Label] = None
    description: Optional[str] = None
    dm_notes: Optional[str] = None
    span: SourceSpan = Field(default_factory=SourceSpan)


# ----- door, window -----

class Door(BaseModel):
    position: Vec2
    connects: list[str] = Field(default_factory=list)
    type: str = "wooden"
    state: str = "closed"
    facing: Optional[str] = None
    width: float = 1.0
    # Trap flag — orthogonal to `state`, so a door can be e.g. closed-and-
    # trapped or locked-and-trapped. GM information: the renderer marks it,
    # but fog-of-war hides it in the players' view until discovered.
    trapped: bool = False
    description: Optional[str] = None
    dm_notes: Optional[str] = None
    span: SourceSpan = Field(default_factory=SourceSpan)


class Window(BaseModel):
    position: Vec2
    in_ref: str
    width: float = 1.0
    description: Optional[str] = None
    span: SourceSpan = Field(default_factory=SourceSpan)


# ----- marker (dynamic tokens: players, monsters, NPCs) -----

class Marker(BaseModel):
    """A named token placed on the map at a specific point.

    Markers are intended for runtime / scene-level tracking (party
    members, monsters, NPCs) rather than the static furniture
    represented by `feature`. The `tag` field drives the rendered
    colour via a built-in palette; any hex string is also accepted
    verbatim for custom colours.
    """
    name: str
    position: Vec2
    tag: str = "neutral"  # palette key OR a CSS color (e.g. "#ff8800")
    label: Optional[str] = None  # display name override (defaults to `name`)
    initial: Optional[str] = None  # letter inside the token (defaults to name[0])
    size: float = 0.5  # token radius in world units
    location: Optional[str] = None  # optional `room.foo` / `corridor.bar` ref
    image: Optional[str] = None  # path or URL to an image; replaces the initial glyph when set
    description: Optional[str] = None
    dm_notes: Optional[str] = None
    span: SourceSpan = Field(default_factory=SourceSpan)


class TextAnnotation(BaseModel):
    """Freestanding text drawn at a fixed map position.

    Unlike a room/corridor `label`, this is a top-level primitive anchored to
    absolute world coordinates. `size` is a multiplier on the renderer's base
    label size (so `size 1` matches a default room label).
    """
    text: str
    position: Vec2
    size: float = 1.0  # multiplier on the renderer's base label size
    rotate: float = 0.0  # degrees, counter-clockwise
    description: Optional[str] = None
    dm_notes: Optional[str] = None
    span: SourceSpan = Field(default_factory=SourceSpan)


class Area(BaseModel):
    """A decorative terrain area — a pool of water, lava, a pit, etc.

    Drawn as a filled shape (reusing the room shape grammar), but it is NOT
    a room: areas are excluded from the connectivity graph and room
    numbering. `kind` selects a built-in fill/outline palette (water, lava,
    pit, …); `background` overrides the fill explicitly (CSS colour or
    texture id). `line_style organic` gives a natural wavy edge.
    """
    name: str
    kind: str = "water"
    shape: RoomShape
    label: Optional[Label] = None
    background: Optional[str] = None  # explicit fill override
    line_style: Optional[str] = None
    line_style_amount: Optional[float] = None
    description: Optional[str] = None
    dm_notes: Optional[str] = None
    span: SourceSpan = Field(default_factory=SourceSpan)


class LineFeature(BaseModel):
    """A styled polyline decoration drawn along a path of points.

    `kind` selects the look: `bars` (dotted line), `curtain` (wavy line),
    `barred` (small `+` marks along the path), `step` (two thin parallel
    lines straddling the path). Not a connector — excluded from the
    connectivity graph.
    """
    name: str
    kind: str = "bars"
    points: list[Vec2] = Field(default_factory=list)
    description: Optional[str] = None
    dm_notes: Optional[str] = None
    span: SourceSpan = Field(default_factory=SourceSpan)


class Exit(BaseModel):
    """A cross-map transition: a point that links to a position on another
    map in the same project.

    Placed at `position` on this map; stepping onto it sends the party to
    `target_map` (the target map's name/id within the project) at
    `target_position`. Unlike a `door` — which connects two nodes *within*
    one map and feeds the connectivity graph — an exit leaves the map
    entirely, so it's not part of the single-map graph. The backend (which
    knows the whole project) resolves `target_map` to the actual map.
    """
    position: Vec2
    target_map: str  # name/id of the destination map within the project
    target_position: Vec2  # landing coordinates on the destination map
    label: Optional[Label] = None  # opt-in on-map label
    # GM-only: stripped from the fogged players' view until discovered, like a
    # secret door or a `secret` feature.
    secret: bool = False
    description: Optional[str] = None
    dm_notes: Optional[str] = None
    span: SourceSpan = Field(default_factory=SourceSpan)


# ----- layer -----

class Layer(BaseModel):
    name: str
    hidden: bool = False
    rooms: list[Room] = Field(default_factory=list)
    corridors: list[Corridor] = Field(default_factory=list)
    slices: list[Slice] = Field(default_factory=list)
    features: list[FeatureInstance] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    texts: list[TextAnnotation] = Field(default_factory=list)
    areas: list[Area] = Field(default_factory=list)
    line_features: list[LineFeature] = Field(default_factory=list)
    exits: list[Exit] = Field(default_factory=list)
    span: SourceSpan = Field(default_factory=SourceSpan)


# ----- top-level map -----

class GridConfig(BaseModel):
    cell_px: int = 32
    unit_name: Optional[str] = None
    unit_per_cell: Optional[float] = None
    bounds_w: float = 60.0
    bounds_h: float = 40.0
    origin: str = "top-left"  # "top-left" | "bottom-left"


class MapConfig(BaseModel):
    name: str
    grid: GridConfig = Field(default_factory=GridConfig)
    renderer: str = "classic-bw"
    theme: Optional[str] = None
    description: Optional[str] = None  # read-aloud intro for the whole map
    dm_notes: Optional[str] = None  # private map-wide notes (hooks, secrets)
    legend: bool = False  # render a symbol legend strip below the map
    # Page-wide background. CSS color string (e.g. "#1a1a1a") OR a built-in
    # texture id (e.g. "stone", "parchment", "water", "grass"). When unset
    # the renderer falls back to its own default (typically white).
    background: Optional[str] = None
    # Map-wide grid overlay: when set, the renderer draws faint grid lines
    # at this world-unit spacing across the full canvas (graph-paper look).
    # `None` (default) = no overlay. Per-room `grid` overlays still work.
    grid_overlay: Optional[float] = None
    grid_overlay_color: Optional[str] = None  # CSS color for the overlay lines
    # Global per-cell grid drawn inside every room and corridor (clipped to
    # their areas). `None` = off; a number = spacing in world units.
    cell_grid: Optional[float] = None
    cell_grid_color: Optional[str] = None  # CSS color for the cell-grid lines
    # Optional party / character starting position (world coords) — where the
    # PCs begin when the map loads. Drawn as a start marker; play-sessions can
    # use it as the default party location.
    party_start: Optional[Vec2] = None
    # Prefix on-map room labels with their sequential number ("1. Hall").
    # `room_numbers off` in the map block turns this off (labels show bare).
    room_numbers: bool = True
    # Map-wide default corridor corner style ("round" | "straight"). Applies
    # to every corridor that doesn't set its own `corners`. `None` (default)
    # means the renderer falls back to "round".
    default_corners: Optional[str] = None
    # Optional on-map title. Uses the same alignment logic as labels (against
    # the full map bbox); defaults to top-centre when no `at`/`align` is given.
    title: Optional[Label] = None
    span: SourceSpan = Field(default_factory=SourceSpan)


# ----- scenario (a bundle of maps + boxed text + DM notes) -----

class ScenarioMapRef(BaseModel):
    """A reference to a .dmap file pulled into a scenario."""
    path: str  # path string as written in the source (resolved by renderer)
    span: SourceSpan = Field(default_factory=SourceSpan)


class Scenario(BaseModel):
    """Adventure-level bundle: prose plus a list of map files."""
    name: str
    description: Optional[str] = None  # player-facing read-aloud / boxed text
    dm_notes: Optional[str] = None  # GM-private notes
    maps: list[ScenarioMapRef] = Field(default_factory=list)
    span: SourceSpan = Field(default_factory=SourceSpan)


class DungeonMap(BaseModel):
    """The root semantic model of a parsed .dmap file."""
    map: MapConfig
    feature_defs: dict[str, FeatureDef] = Field(default_factory=dict)
    rooms: dict[str, Room] = Field(default_factory=dict)
    corridors: dict[str, Corridor] = Field(default_factory=dict)
    slices: dict[str, Slice] = Field(default_factory=dict)
    features: list[FeatureInstance] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    texts: list[TextAnnotation] = Field(default_factory=list)
    areas: list[Area] = Field(default_factory=list)
    line_features: list[LineFeature] = Field(default_factory=list)
    exits: list[Exit] = Field(default_factory=list)
    layers: list[Layer] = Field(default_factory=list)
    # Set on files whose top-level construct is `scenario "..." { ... }`
    # instead of (or as well as) a `map { ... }` block.
    scenario: Optional["Scenario"] = None
