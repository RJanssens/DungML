"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ----- auth -----

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: EmailStr
    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    token: str
    user: UserOut


# ----- projects -----

class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ----- maps -----

class MapCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source: str = ""


class MapUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    source: str | None = None


class MapSummaryOut(BaseModel):
    id: str
    project_id: str
    name: str
    # "map" (has a `map "..." { ... }` block, renderable) vs "library"
    # (include-only — feature_defs / shared declarations only).
    kind: Literal["map", "library"] = "map"
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class MapOut(MapSummaryOut):
    source: str


class LibraryCatalogEntry(BaseModel):
    # A bundled include library and whether this project already has an
    # editable copy of it.
    name: str
    added: bool


class ImportLibraryIn(BaseModel):
    name: str


# ----- dsl -----

class SourceIn(BaseModel):
    source: str


class RenderIn(BaseModel):
    source: str
    renderer: str | None = None


class MapRenderIn(BaseModel):
    # When omitted, the stored map source is used. The editor passes its
    # live (possibly unsaved) buffer so includes resolve against the
    # project while previewing edits.
    source: str | None = None
    renderer: str | None = None


class MapValidateIn(BaseModel):
    source: str | None = None


class FeatureGroup(BaseModel):
    # Features contributed by one source (an include filename, or the
    # "(this file)" local group). Names sorted alphabetically.
    source: str
    names: list[str]


class FeatureNamesOut(BaseModel):
    # Feature_def names available to a map (local defs + everything its
    # includes resolve to). `names` is the flat sorted union; `groups`
    # splits them by source file (each sorted), for a grouped dropdown.
    names: list[str]
    groups: list[FeatureGroup]


class DiagnosticOut(BaseModel):
    severity: Literal["error", "warning"]
    message: str
    line: int = 0
    column: int = 0
    end_line: int = 0
    end_column: int = 0


class ValidateOut(BaseModel):
    diagnostics: list[DiagnosticOut]


class RenderOut(BaseModel):
    svg: str
    diagnostics: list[DiagnosticOut]


class NodeConnection(BaseModel):
    to: str  # neighbour node id, or "(exterior)" for a boundary exit
    type: str  # door type
    state: str  # door state
    direction: Literal["both", "out", "in"]  # one-way doors are "out"/"in"


class NodeConnectivity(BaseModel):
    id: str  # "room.hall" / "corridor.c1"
    kind: Literal["room", "corridor"]
    name: str
    connected: bool  # has at least one door (edge or boundary exit)
    doors: int  # number of doors touching this node
    connections: list[NodeConnection] = []


class ConnectivityOut(BaseModel):
    nodes: list[NodeConnectivity]


class ParseErrorOut(BaseModel):
    message: str
    line: int = 0
    column: int = 0


class ParseOut(BaseModel):
    map: dict  # parsed DungeonMap as JSON
    error: ParseErrorOut | None = None
