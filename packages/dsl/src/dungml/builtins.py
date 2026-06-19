"""Built-in feature names that are valid `feature <name>` references
without an explicit `feature_def`. Renderers are expected to know how
to draw all of these.
"""

DUNGEON_FEATURES = {
    "pillar",
    "rubble",
    "chest",
    "altar",
    "pit-trap",
    "trap",  # back-compat alias for pit-trap
    "pit",
    "floor-trapdoor",
    "ceiling-trapdoor",
    "dart-trap",
    "fire-trap",
    "portcullis",
    "stairs-up",
    "stairs-down",
    "stairs-left",
    "stairs-right",
    "stairs-spiral",
    "spiral-stairs",
    "fountain",
    "water",
    "brazier",
    "statue",
    "marker",
}

BUILDING_FEATURES = {
    "hearth",
    "stove",
    "table",
    "chair",
    "bed",
    "desk",
    "bookshelf",
    "bath",
    "wardrobe",
    "barrel",
    "crate",
}

# Terrain features — bridges, fords, etc. — typically placed on top of
# a `slice` to indicate a crossing point.
TERRAIN_FEATURES = {
    "bridge",
}

BUILTIN_FEATURES: frozenset[str] = frozenset(
    DUNGEON_FEATURES | BUILDING_FEATURES | TERRAIN_FEATURES
)
