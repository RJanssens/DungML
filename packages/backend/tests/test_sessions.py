"""Play-session REST routes: create, move (reveal-on-move), render fog-of-war."""
from __future__ import annotations

import pytest

MAP_SRC = """
map "M" { grid { cell 20 px bounds 30 x 30 } renderer "classic-bw" }
room "a" { rect 0,0 6 x 6 label "A" }
room "b" { rect 12,0 6 x 6 label "B" }
corridor "c1" { width 1 node n1 at 6,3 node n2 at 12,3 run n1 to n2 }
door at 6,3 { connects room.a, corridor.c1 type wooden }
door at 12,3 { connects corridor.c1, room.b type wooden }
"""


@pytest.fixture
def map_id(auth_client) -> str:
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    r = auth_client.post(
        f"/api/projects/{pid}/maps", json={"name": "M", "source": MAP_SRC}
    )
    return r.json()["id"]


def test_create_session_reveals_start(auth_client, map_id):
    r = auth_client.post(
        f"/api/maps/{map_id}/sessions",
        json={"name": "Run 1", "start_location": "room.a"},
    )
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["party_location"] == "room.a"
    assert "room.a" in s["discovered_nodes"]
    assert "room.b" not in s["discovered_nodes"]  # not yet explored
    # exits offered from A: the corridor.
    tos = {e["to"] for e in s["exits"]}
    assert "corridor.c1" in tos


def test_create_rejects_unknown_start(auth_client, map_id):
    r = auth_client.post(
        f"/api/maps/{map_id}/sessions",
        json={"name": "x", "start_location": "room.zzz"},
    )
    assert r.status_code == 400


def test_move_reveals_destination(auth_client, map_id):
    sid = auth_client.post(
        f"/api/maps/{map_id}/sessions",
        json={"name": "r", "start_location": "room.a"},
    ).json()["id"]
    r = auth_client.post(f"/api/sessions/{sid}/move", json={"to": "corridor.c1"})
    assert r.status_code == 200
    s = r.json()
    assert s["party_location"] == "corridor.c1"
    assert "corridor.c1" in s["discovered_nodes"]
    # standing in the corridor now reveals the door to B (frontier).
    assert "12,3" in s["discovered_doors"]


def test_render_fog_hides_unexplored(auth_client, map_id):
    sid = auth_client.post(
        f"/api/maps/{map_id}/sessions",
        json={"name": "r", "start_location": "room.a"},
    ).json()["id"]
    svg = auth_client.get(f"/api/sessions/{sid}/render").json()["svg"]
    assert 'data-room="a"' in svg
    assert 'data-room="b"' not in svg
    assert "party-start" in svg  # party marker tracks location


def test_render_full_view_shows_all(auth_client, map_id):
    sid = auth_client.post(
        f"/api/maps/{map_id}/sessions",
        json={"name": "r", "start_location": "room.a"},
    ).json()["id"]
    svg = auth_client.get(f"/api/sessions/{sid}/render?view=full").json()["svg"]
    assert 'data-room="a"' in svg and 'data-room="b"' in svg


def test_list_and_delete(auth_client, map_id):
    sid = auth_client.post(
        f"/api/maps/{map_id}/sessions", json={"name": "r"}
    ).json()["id"]
    assert any(s["id"] == sid for s in auth_client.get(f"/api/maps/{map_id}/sessions").json())
    assert auth_client.delete(f"/api/sessions/{sid}").status_code == 204
    assert auth_client.get(f"/api/sessions/{sid}").status_code == 404


def test_ownership_enforced(client, auth_client, map_id):
    sid = auth_client.post(
        f"/api/maps/{map_id}/sessions", json={"name": "r"}
    ).json()["id"]
    # A different user must not see another's session.
    other = client.post(
        "/api/auth/register", json={"email": "other@x.com", "password": "longenough"}
    ).json()
    r = client.get(
        f"/api/sessions/{sid}",
        headers={"Authorization": f"Bearer {other['token']}"},
    )
    assert r.status_code == 404
