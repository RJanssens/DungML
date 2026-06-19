"""End-to-end smoke tests for the MCP server.

We bypass the MCP transport (stdio) and call the tool functions directly
on an isolated SQLite DB. Each test gets its own temp file so they don't
collide and don't touch the developer's real ./dungml.db.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point dungml-backend at a temp SQLite file and re-init the schema.

    The dungml_mcp.server module is reloaded so the cached sessionmaker
    (built lazily on first DB access) picks up the new URL. The MCP user
    is re-provisioned in each fresh DB.
    """
    db_path = tmp_path / "mcp_test.db"
    monkeypatch.setenv("DUNGML_DB_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("DUNGML_MCP_USER_EMAIL", "mcp@test")
    monkeypatch.setenv("DUNGML_MCP_USER_PASSWORD", "test-password-12345")

    from dungml_backend import config as backend_config
    from dungml_backend import db as backend_db

    # Force config + engine to re-read env vars.
    backend_config.settings = backend_config.reload_settings()
    backend_db.reset_engine()
    backend_db.init_schema()

    server = importlib.reload(importlib.import_module("dungml_mcp.server"))
    return server


def _unwrap(tool_decorated):
    """FastMCP wraps the original function in a Pydantic-validated callable
    on the tool registry. The underlying Python function is still callable
    directly because @mcp.tool() returns the original (the decorator
    register-then-returns)."""
    return tool_decorated


def test_create_and_list_projects(fresh_db):
    s = fresh_db
    assert s.list_projects() == []
    p = s.create_project(name="Demo Adventure")
    assert "id" in p and p["name"] == "Demo Adventure"
    rows = s.list_projects()
    assert len(rows) == 1
    assert rows[0]["id"] == p["id"]


def test_full_map_lifecycle(fresh_db):
    s = fresh_db
    project = s.create_project(name="Lifecycle")
    pid = project["id"]

    # Empty to start
    assert s.list_maps(project_id=pid) == []

    # Create a renderable map
    src = """
    map "Hut" {
      grid { bounds 20 x 20 }
      legend
    }
    room "r" { rect 2,2 8 x 8 label "Room" }
    """
    created = s.create_map(project_id=pid, name="Hut", source=src)
    mid = created["id"]
    assert created["kind"] == "map"

    # Fetch full source
    full = s.get_map(map_id=mid)
    assert full["source"].strip().startswith('map "Hut"')

    # Patch the name only
    updated = s.update_map(map_id=mid, name="Renamed Hut")
    assert updated["name"] == "Renamed Hut"

    # Render — should return SVG and zero error-diagnostics
    rendered = s.render_map(map_id=mid)
    assert rendered["svg"].startswith("<svg")
    assert not any(d["severity"] == "error" for d in rendered["diagnostics"])

    # Delete it
    s.delete_map(map_id=mid)
    assert s.list_maps(project_id=pid) == []


def test_render_with_inline_source_no_map_id(fresh_db):
    s = fresh_db
    rendered = s.render_map(
        source='map "X" { grid { bounds 10 x 10 } } room "r" { rect 1,1 5 x 5 }'
    )
    assert "<svg" in rendered["svg"]


def test_render_requires_exactly_one_of_id_or_source(fresh_db):
    s = fresh_db
    with pytest.raises(ValueError, match="exactly one"):
        s.render_map()
    with pytest.raises(ValueError, match="exactly one"):
        s.render_map(map_id="x", source="y")


def test_validate_source_reports_parse_error(fresh_db):
    s = fresh_db
    result = s.validate_source(source="not a valid .dmap file")
    assert result["ok"] is False
    assert result["error"] is not None


def test_validate_source_accepts_valid_map(fresh_db):
    s = fresh_db
    result = s.validate_source(
        source='map "Y" { grid { bounds 10 x 10 } } room "r" { rect 0,0 5 x 5 }'
    )
    assert result["ok"] is True
    assert "error" not in result


def test_list_renderer_names_includes_classic_bw(fresh_db):
    s = fresh_db
    names = s.list_renderer_names()
    assert "classic-bw" in names
    assert "hatched" in names


def test_delete_project_cascades_to_maps(fresh_db):
    s = fresh_db
    project = s.create_project(name="Doomed")
    s.create_map(project_id=project["id"], name="will-die")
    s.delete_project(project_id=project["id"])
    assert s.list_projects() == []


def test_unknown_map_id_raises(fresh_db):
    s = fresh_db
    with pytest.raises(ValueError, match="not found"):
        s.get_map(map_id="nonexistent-uuid")


def test_update_map_requires_at_least_one_field(fresh_db):
    s = fresh_db
    p = s.create_project(name="P")
    m = s.create_map(project_id=p["id"], name="m")
    with pytest.raises(ValueError, match="at least one"):
        s.update_map(map_id=m["id"])


# ----- play-session / pathfinding tools -----

_SESSION_MAP = """
map "Dungeon" { grid { bounds 60 x 40 } }
room "antechamber" { rect 2,4 12 x 10 label "Ante" }
room "sanctum"     { rect 18,4 10 x 10 label "Sanctum" }
room "vault"       { rect 30,4 8 x 8 label "Vault" }
corridor "passage" { width 2 segment line from 14,9 to 18,9 }
door at 14,9 { connects room.antechamber, corridor.passage }
door at 18,9 { connects room.sanctum, corridor.passage  state locked  type iron }
door at 28,7 { connects room.sanctum, room.vault }
door at 8,14 { connects room.antechamber  type secret }
"""


@pytest.fixture
def session_map(fresh_db):
    s = fresh_db
    p = s.create_project(name="Campaign")
    m = s.create_map(project_id=p["id"], name="Dungeon", source=_SESSION_MAP)
    return s, m["id"]


def test_create_session_with_start_location_reveals_node(session_map):
    s, mid = session_map
    sess = s.create_session(
        map_id=mid, name="Party A", start_location="room.antechamber"
    )
    assert sess["party_location"] == "room.antechamber"
    assert "room.antechamber" in sess["discovered_nodes"]
    # The visible door to the passage is revealed; the secret door is not.
    assert "14,9" in sess["discovered_doors"]
    assert "8,14" not in sess["discovered_doors"]


def test_create_session_rejects_unknown_start(session_map):
    s, mid = session_map
    with pytest.raises(ValueError, match="unknown node"):
        s.create_session(map_id=mid, name="X", start_location="room.nope")


def test_get_exits_discovered_vs_any(session_map):
    s, mid = session_map
    sess = s.create_session(
        map_id=mid, name="P", start_location="room.antechamber"
    )
    sid = sess["id"]
    disc = s.get_exits(session_id=sid, node="room.antechamber", mode="discovered")
    doors = {e["door"] for e in disc["exits"]}
    assert "14,9" in doors and "8,14" not in doors  # secret not yet found
    any_ex = s.get_exits(session_id=sid, node="room.antechamber", mode="any")
    assert "8,14" in {e["door"] for e in any_ex["exits"]}


def test_find_path_discovered_blocked_by_locked_then_opened(session_map):
    s, mid = session_map
    sess = s.create_session(
        map_id=mid, name="P", start_location="room.antechamber"
    )
    sid = sess["id"]
    # Explore into the passage, then sanctum.
    s.set_party_location(session_id=sid, location="corridor.passage")
    s.set_party_location(session_id=sid, location="room.sanctum")
    # The 18,9 door is locked → no discovered route ante→sanctum yet.
    blocked = s.find_path(
        session_id=sid, from_node="room.antechamber", to_node="room.sanctum",
        mode="discovered",
    )
    assert blocked["found"] is False
    # Unlock it → route opens up.
    s.mark_door(session_id=sid, door="18,9", state="open")
    ok = s.find_path(
        session_id=sid, from_node="room.antechamber", to_node="room.sanctum",
        mode="discovered",
    )
    assert ok["found"] is True
    assert ok["nodes"][0] == "room.antechamber"
    assert ok["nodes"][-1] == "room.sanctum"


def test_find_path_any_ignores_locks_and_discovery(session_map):
    s, mid = session_map
    sess = s.create_session(map_id=mid, name="P")  # nothing discovered
    sid = sess["id"]
    res = s.find_path(
        session_id=sid, from_node="room.antechamber", to_node="room.vault",
        mode="any",
    )
    assert res["found"] is True
    assert res["nodes"][-1] == "room.vault"
    assert res["length"] == 3


def test_get_known_map_frontier(session_map):
    s, mid = session_map
    sess = s.create_session(
        map_id=mid, name="P", start_location="room.antechamber"
    )
    sid = sess["id"]
    known = s.get_known_map(session_id=sid)
    assert known["party_location"] == "room.antechamber"
    assert [n["id"] for n in known["nodes"]] == ["room.antechamber"]
    # The passage door is known but its far side isn't explored → frontier.
    fronts = {f["leads_to"] for f in known["frontier"]}
    assert "corridor.passage" in fronts


def test_render_session_fog_of_war_hides_undiscovered(session_map):
    s, mid = session_map
    sess = s.create_session(
        map_id=mid, name="P", start_location="room.antechamber"
    )
    sid = sess["id"]
    fog = s.render_session(session_id=sid, mode="discovered")
    assert fog["svg"].startswith("<svg")
    # "Sanctum" label belongs to an undiscovered room → absent under fog.
    assert "Sanctum" not in fog["svg"]
    assert "Ante" in fog["svg"]
    full = s.render_session(session_id=sid, mode="full")
    assert "Sanctum" in full["svg"]


def test_mark_door_unknown_raises(session_map):
    s, mid = session_map
    sess = s.create_session(map_id=mid, name="P")
    with pytest.raises(ValueError, match="unknown door"):
        s.mark_door(session_id=sess["id"], door="99,99")


def test_session_lifecycle_list_and_delete(session_map):
    s, mid = session_map
    sess = s.create_session(map_id=mid, name="P")
    assert len(s.list_sessions(map_id=mid)) == 1
    s.delete_session(session_id=sess["id"])
    assert s.list_sessions(map_id=mid) == []


# ----- structured authoring tools -----

_SEED_MAP = 'map "Built" { grid { bounds 20 x 20 } }\nroom "start" { rect 4,4 8 x 8 label "Start" }\n'


@pytest.fixture
def seed_map(fresh_db):
    s = fresh_db
    p = s.create_project(name="Build")
    m = s.create_map(project_id=p["id"], name="Built", source=_SEED_MAP)
    return s, m["id"]


def test_add_room_east_places_and_connects(seed_map):
    s, mid = seed_map
    res = s.add_room(
        map_id=mid, name="hall", width=6, height=6,
        anchor="room.start", direction="east", label="Hall",
    )
    assert res["node"] == "room.hall"
    # start spans x 4..12; hall sits to the east of x=12.
    assert res["bbox"][0] >= 12
    assert len(res["new_doors"]) == 1
    # The map now parses and the two rooms are connected.
    src = s.get_map(map_id=mid)["source"]
    assert 'room "hall"' in src
    g_check = s.validate_source(source=src)
    assert g_check["ok"] is True


def test_add_room_grows_bounds(seed_map):
    s, mid = seed_map
    # Push a room far east so it would exceed the 20x20 bounds.
    s.add_room(map_id=mid, name="far", width=10, height=6,
               anchor="room.start", direction="east", gap=8)
    src = s.get_map(map_id=mid)["source"]
    import re
    w = float(re.search(r"bounds\s+([\d.]+)\s*x", src).group(1))
    assert w > 20  # bounds expanded to fit


def test_add_room_with_gap_inserts_corridor(seed_map):
    s, mid = seed_map
    res = s.add_room(map_id=mid, name="annex", width=6, height=6,
                     anchor="room.start", direction="south", gap=4)
    assert "corridor.start_to_annex" in res["new_nodes"]
    assert len(res["new_doors"]) == 2


def test_add_room_rejects_bad_name(seed_map):
    s, mid = seed_map
    with pytest.raises(ValueError, match="bare identifier"):
        s.add_room(map_id=mid, name="north hall", width=4, height=4,
                   anchor="room.start", direction="north")


def test_add_room_rejects_negative_placement(seed_map):
    s, mid = seed_map
    # start is at x=4; a width-10 room to its west lands at x=-6.
    with pytest.raises(ValueError, match="past the map origin"):
        s.add_room(map_id=mid, name="west_wing", width=10, height=4,
                   anchor="room.start", direction="west")


def test_add_corridor_links_two_rooms(seed_map):
    s, mid = seed_map
    s.add_room(map_id=mid, name="east_room", width=6, height=6,
               anchor="room.start", direction="east", gap=6, connect=False)
    res = s.add_corridor(map_id=mid, name="link",
                         from_node="room.start", to_node="room.east_room")
    assert res["node"] == "corridor.link"
    assert len(res["new_doors"]) == 2
    assert s.validate_source(source=s.get_map(map_id=mid)["source"])["ok"]


def test_add_door_between_nodes(seed_map):
    s, mid = seed_map
    s.add_room(map_id=mid, name="hall", width=6, height=8,
               anchor="room.start", direction="east", connect=False)
    res = s.add_door(map_id=mid, between=["room.start", "room.hall"],
                     type="iron", state="locked")
    assert "," in res["door"]
    assert res["connects"] == ["room.start", "room.hall"]


def test_add_room_invalid_edit_not_saved(seed_map):
    s, mid = seed_map
    before = s.get_map(map_id=mid)["source"]
    with pytest.raises(ValueError, match="already exists"):
        s.add_room(map_id=mid, name="start", width=4, height=4, position="14,14")
    assert s.get_map(map_id=mid)["source"] == before  # unchanged


def test_build_then_pathfind_and_discover(seed_map):
    """End-to-end: build out a map, then use a session to pathfind over it."""
    s, mid = seed_map
    sess = s.create_session(map_id=mid, name="cartographers",
                            start_location="room.start")
    sid = sess["id"]
    # The party builds eastward as they explore, revealing as they go.
    s.add_room(map_id=mid, name="hall", width=6, height=6,
               anchor="room.start", direction="east", discover_in_session=sid)
    s.add_room(map_id=mid, name="vault", width=5, height=5,
               anchor="room.hall", direction="east", discover_in_session=sid)
    # Discovered route start -> hall -> vault exists now.
    path = s.find_path(session_id=sid, from_node="room.start",
                       to_node="room.vault", mode="discovered")
    assert path["found"] is True
    assert path["nodes"][0] == "room.start"
    assert path["nodes"][-1] == "room.vault"
