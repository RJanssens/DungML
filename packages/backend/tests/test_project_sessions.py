"""Seeing how far every session in a project has got, without opening each map.

Progress already existed per-map inside the play view; these two reads lift it
to the project, where the GM actually looks: the campaign row carries the map's
node total so a count becomes a fraction, and one call lists every session
across the project's maps.
"""
from __future__ import annotations

OWNER = {"Authorization": "Bearer dev-user"}
SVC = {"Authorization": "Bearer dev-service"}
OTHER_SUBJECT = "@dungeon-daemon-service"

EXT = "return-to-stonehell"


def _project(client, name="Stonehell") -> str:
    return client.post("/api/projects", json={"name": name}, headers=OWNER).json()["id"]


def _map(client, pid: str, name: str, source: str) -> str:
    return client.post(
        f"/api/projects/{pid}/maps", json={"name": name, "source": source}, headers=OWNER
    ).json()["id"]


def _node_count(client, map_id: str) -> int:
    return len(client.get(f"/maps/{map_id}/rooms", headers=SVC).json()["rooms"])


def _a_room(client, map_id: str) -> str:
    return client.get(f"/maps/{map_id}/rooms", headers=SVC).json()["rooms"][0]["id"]


# ---- totals on the campaign row ----


def test_campaign_row_carries_the_maps_node_total(client, cottage_source):
    pid = _project(client)
    mid = _map(client, pid, "Gatehouse", cottage_source)
    client.post(f"/campaigns/{EXT}/link", json={"project_id": pid}, headers=OWNER)
    client.put(f"/campaigns/{EXT}/active", json={"map_id": mid}, headers=SVC)
    client.post(
        f"/campaigns/{EXT}/maps/{mid}/party",
        json={"room_id": _a_room(client, mid)},
        headers=SVC,
    )

    row = client.get(f"/api/projects/{pid}/campaigns", headers=OWNER).json()[0]
    assert row["total_nodes"] == _node_count(client, mid)
    assert 0 < row["discovered_nodes"] <= row["total_nodes"]


def test_campaign_row_without_a_map_reports_no_total(client, cottage_source):
    pid = _project(client)
    _map(client, pid, "Gatehouse", cottage_source)
    client.post(f"/campaigns/{EXT}/link", json={"project_id": pid}, headers=OWNER)

    row = client.get(f"/api/projects/{pid}/campaigns", headers=OWNER).json()[0]
    assert row["total_nodes"] == 0


# ---- the project-wide session index ----


def test_lists_sessions_across_every_map_in_the_project(client, cottage_source, crypt_source):
    pid = _project(client)
    m1 = _map(client, pid, "Gatehouse", cottage_source)
    m2 = _map(client, pid, "Crypt", crypt_source)
    client.post(f"/api/maps/{m1}/sessions", json={"name": "Tuesday group"}, headers=OWNER)
    client.post(f"/api/maps/{m2}/sessions", json={"name": "One-shot"}, headers=OWNER)

    rows = client.get(f"/api/projects/{pid}/sessions", headers=OWNER).json()
    assert {r["name"] for r in rows} == {"Tuesday group", "One-shot"}
    assert {r["map_name"] for r in rows} == {"Gatehouse", "Crypt"}


def test_each_row_reports_progress_and_where_the_party_is(client, cottage_source):
    pid = _project(client)
    mid = _map(client, pid, "Gatehouse", cottage_source)
    room = _a_room(client, mid)
    client.post(
        f"/api/maps/{mid}/sessions",
        json={"name": "Tuesday group", "start_location": room},
        headers=OWNER,
    )

    row = client.get(f"/api/projects/{pid}/sessions", headers=OWNER).json()[0]
    assert row["party_location"] == room
    assert row["discovered_nodes"] == 1
    assert row["total_nodes"] == _node_count(client, mid)
    assert row["map_id"] == mid
    assert row["session_id"]


def test_marks_which_sessions_an_external_campaign_drives(client, cottage_source):
    pid = _project(client)
    mid = _map(client, pid, "Gatehouse", cottage_source)
    client.post(f"/api/maps/{mid}/sessions", json={"name": "Tuesday group"}, headers=OWNER)
    client.post(f"/campaigns/{EXT}/link", json={"project_id": pid}, headers=OWNER)
    client.post(
        f"/campaigns/{EXT}/maps/{mid}/party",
        json={"room_id": _a_room(client, mid)},
        headers=SVC,
    )

    rows = client.get(f"/api/projects/{pid}/sessions", headers=OWNER).json()
    driven = {r["name"]: r["external_id"] for r in rows}
    assert driven[f"ttrpg2 · {EXT}"] == EXT
    assert driven["Tuesday group"] is None


def test_a_project_with_no_sessions_lists_nothing(client, cottage_source):
    pid = _project(client)
    _map(client, pid, "Gatehouse", cottage_source)
    assert client.get(f"/api/projects/{pid}/sessions", headers=OWNER).json() == []


def test_an_unparseable_map_does_not_break_the_index(client, cottage_source):
    """A map mid-edit shouldn't 500 the project view — it just has no total."""
    pid = _project(client)
    good = _map(client, pid, "Gatehouse", cottage_source)
    broken = _map(client, pid, "Broken", 'map "x" { grid { bounds oops } ')
    client.post(f"/api/maps/{good}/sessions", json={"name": "Fine"}, headers=OWNER)
    from dungml_backend import models
    from dungml_backend.db import get_sessionmaker

    db = get_sessionmaker()()
    try:
        db.add(models.PlaySession(map_id=broken, name="On a broken map"))
        db.commit()
    finally:
        db.close()

    rows = client.get(f"/api/projects/{pid}/sessions", headers=OWNER).json()
    by_name = {r["name"]: r for r in rows}
    assert by_name["On a broken map"]["total_nodes"] == 0
    assert by_name["Fine"]["total_nodes"] > 0


def test_the_index_is_visible_to_a_member_and_hidden_from_outsiders(client, cottage_source):
    pid = _project(client)
    _map(client, pid, "Gatehouse", cottage_source)
    elsewhere = _project(client, name="Unrelated")

    assert client.get("/api/projects", headers=SVC).status_code == 200
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )
    assert client.get(f"/api/projects/{pid}/sessions", headers=SVC).status_code == 200
    assert client.get(f"/api/projects/{elsewhere}/sessions", headers=SVC).status_code == 404
