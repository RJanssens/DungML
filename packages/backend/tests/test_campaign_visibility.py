"""Making an external campaign's play session findable from the GUI.

Three things the web app needs and didn't have: a session name that says
which campaign drives it, a record of which map that campaign is currently
on, and one read that ties them together for a project.
"""
from __future__ import annotations

OWNER = {"Authorization": "Bearer dev-user"}
OTHER = {"Authorization": "Bearer dev-service"}
SVC = {"Authorization": "Bearer dev-service"}
OTHER_SUBJECT = "@dungeon-daemon-service"

EXT = "return-to-stonehell"


def _linked_project(client, cottage_source: str) -> tuple[str, str]:
    """A project with one map, linked to campaign EXT. Returns (pid, map_id)."""
    pid = client.post(
        "/api/projects", json={"name": "Stonehell"}, headers=OWNER
    ).json()["id"]
    mid = client.post(
        f"/api/projects/{pid}/maps",
        json={"name": "Gatehouse", "source": cottage_source},
        headers=OWNER,
    ).json()["id"]
    assert client.post(
        f"/campaigns/{EXT}/link", json={"project_id": pid}, headers=OWNER
    ).status_code == 200
    return pid, mid


def _a_room(client, map_id: str) -> str:
    rooms = client.get(f"/maps/{map_id}/rooms", headers=SVC).json()["rooms"]
    return rooms[0]["id"]


def test_campaign_session_is_named_after_the_campaign(client, cottage_source):
    pid, mid = _linked_project(client, cottage_source)
    room = _a_room(client, mid)
    client.post(f"/campaigns/{EXT}/maps/{mid}/party", json={"room_id": room}, headers=SVC)

    names = [s["name"] for s in client.get(f"/api/maps/{mid}/sessions", headers=OWNER).json()]
    assert names == [f"ttrpg2 · {EXT}"]


def test_a_legacy_party_session_is_renamed_on_next_contact(client, cottage_source):
    """Sessions created before this change are all called "party"; they get
    their campaign name the next time ttrpg2 touches them."""
    pid, mid = _linked_project(client, cottage_source)
    from dungml_backend import models
    from dungml_backend.db import get_sessionmaker

    db = get_sessionmaker()()
    try:
        db.add(models.PlaySession(map_id=mid, external_id=EXT, name="party"))
        db.commit()
    finally:
        db.close()

    room = _a_room(client, mid)
    client.post(f"/campaigns/{EXT}/maps/{mid}/party", json={"room_id": room}, headers=SVC)

    sessions = client.get(f"/api/maps/{mid}/sessions", headers=OWNER).json()
    assert [s["name"] for s in sessions] == [f"ttrpg2 · {EXT}"]


def test_a_session_the_gm_renamed_is_left_alone(client, cottage_source):
    pid, mid = _linked_project(client, cottage_source)
    from dungml_backend import models
    from dungml_backend.db import get_sessionmaker

    db = get_sessionmaker()()
    try:
        db.add(models.PlaySession(map_id=mid, external_id=EXT, name="Tuesday group"))
        db.commit()
    finally:
        db.close()

    room = _a_room(client, mid)
    client.post(f"/campaigns/{EXT}/maps/{mid}/party", json={"room_id": room}, headers=SVC)

    sessions = client.get(f"/api/maps/{mid}/sessions", headers=OWNER).json()
    assert [s["name"] for s in sessions] == ["Tuesday group"]


def test_service_records_the_campaigns_active_map(client, cottage_source):
    pid, mid = _linked_project(client, cottage_source)
    r = client.put(f"/campaigns/{EXT}/active", json={"map_id": mid}, headers=SVC)
    assert r.status_code == 200
    assert r.json()["active_map_id"] == mid


def test_active_map_must_belong_to_the_linked_project(client, cottage_source):
    pid, mid = _linked_project(client, cottage_source)
    other_pid = client.post(
        "/api/projects", json={"name": "Elsewhere"}, headers=OWNER
    ).json()["id"]
    stray = client.post(
        f"/api/projects/{other_pid}/maps",
        json={"name": "Stray", "source": cottage_source},
        headers=OWNER,
    ).json()["id"]

    r = client.put(f"/campaigns/{EXT}/active", json={"map_id": stray}, headers=SVC)
    assert r.status_code == 404


def test_recording_the_active_map_needs_a_service_principal(client, cottage_source):
    pid, mid = _linked_project(client, cottage_source)
    r = client.put(f"/campaigns/{EXT}/active", json={"map_id": mid}, headers=OWNER)
    assert r.status_code == 403


def test_project_campaigns_reports_the_live_session(client, cottage_source):
    pid, mid = _linked_project(client, cottage_source)
    room = _a_room(client, mid)
    client.put(f"/campaigns/{EXT}/active", json={"map_id": mid}, headers=SVC)
    client.post(f"/campaigns/{EXT}/maps/{mid}/party", json={"room_id": room}, headers=SVC)

    rows = client.get(f"/api/projects/{pid}/campaigns", headers=OWNER).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["external_id"] == EXT
    assert row["active_map_id"] == mid
    assert row["active_map_name"] == "Gatehouse"
    assert row["party_location"] == room
    assert row["discovered_nodes"] >= 1
    assert row["session_id"]


def test_project_campaigns_is_empty_before_a_locale_is_chosen(client, cottage_source):
    pid, _mid = _linked_project(client, cottage_source)
    rows = client.get(f"/api/projects/{pid}/campaigns", headers=OWNER).json()
    assert len(rows) == 1
    assert rows[0]["active_map_id"] is None
    assert rows[0]["session_id"] is None


def test_project_campaigns_is_visible_to_a_member(client, cottage_source):
    pid, mid = _linked_project(client, cottage_source)
    assert client.get("/api/projects", headers=OTHER).status_code == 200
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )
    assert client.get(f"/api/projects/{pid}/campaigns", headers=OTHER).status_code == 200


def test_project_campaigns_hidden_without_access(client, cottage_source):
    """The service token can see a project it drives a campaign on — that's
    the membership a link grants. It must still see nothing elsewhere."""
    pid, _mid = _linked_project(client, cottage_source)
    elsewhere = client.post(
        "/api/projects", json={"name": "Unrelated"}, headers=OWNER
    ).json()["id"]

    assert client.get(f"/api/projects/{pid}/campaigns", headers=SVC).status_code == 200
    assert (
        client.get(f"/api/projects/{elsewhere}/campaigns", headers=SVC).status_code
        == 404
    )
