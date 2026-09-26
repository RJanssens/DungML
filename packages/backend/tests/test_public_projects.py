"""Public projects: every signed-in user gets member rights on a public one.

`dev-service` stands in for "another user", as in test_project_members.py —
static auth ships two principals.
"""
from __future__ import annotations

import sqlite3

import pytest

from dungml_backend import contract, db, models

OWNER = {"Authorization": "Bearer dev-user"}
OTHER = {"Authorization": "Bearer dev-service"}


def _row(pid: str) -> models.Project:
    return db.get_sessionmaker()().get(models.Project, pid)


# ---- Task 1: storage and defaults ----


def test_new_project_is_public_by_default(client):
    pid = client.post("/api/projects", json={"name": "P"}, headers=OWNER).json()["id"]
    assert _row(pid).is_public is True


def test_project_can_be_created_private(client):
    pid = client.post(
        "/api/projects", json={"name": "P", "is_public": False}, headers=OWNER
    ).json()["id"]
    assert _row(pid).is_public is False


def test_example_project_is_private(client):
    pid = client.post("/api/projects/import-samples", headers=OWNER).json()["id"]
    assert _row(pid).is_public is False


def test_service_project_is_private(client):
    s = db.get_sessionmaker()()
    m = contract.get_or_create_map(s, "combat-1")
    assert s.get(models.Project, m.project_id).is_public is False


def test_migration_makes_existing_public_except_service_and_examples(client, db_path):
    ordinary = client.post("/api/projects", json={"name": "Ordinary"}, headers=OWNER).json()["id"]
    example = client.post("/api/projects/import-samples", headers=OWNER).json()["id"]
    s = db.get_sessionmaker()()
    service = contract.get_or_create_map(s, "combat-1").project_id
    s.close()
    # an ordinary project the owner once named like the service project stays public:
    lookalike = client.post(
        "/api/projects", json={"name": contract._SERVICE_PROJECT}, headers=OWNER
    ).json()["id"]
    with sqlite3.connect(db_path) as con:
        con.execute("ALTER TABLE projects DROP COLUMN is_public")   # a pre-feature DB

    db.ensure_columns()

    with sqlite3.connect(db_path) as con:
        got = dict(con.execute("SELECT id, is_public FROM projects").fetchall())
    assert got == {ordinary: 1, example: 0, service: 0, lookalike: 1}


def test_migration_runs_once_so_an_owner_choice_sticks(client, db_path):
    example = client.post("/api/projects/import-samples", headers=OWNER).json()["id"]
    with sqlite3.connect(db_path) as con:
        con.execute("ALTER TABLE projects DROP COLUMN is_public")
    db.ensure_columns()
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE projects SET is_public = 1 WHERE id = ?", (example,))
    db.ensure_columns()   # every boot calls it
    assert _row(example).is_public is True


# ---- Task 2: access ----


def _public(client, name="Pub") -> str:
    return client.post("/api/projects", json={"name": name}, headers=OWNER).json()["id"]


def _private(client, name="Priv") -> str:
    return client.post(
        "/api/projects", json={"name": name, "is_public": False}, headers=OWNER
    ).json()["id"]


def test_stranger_sees_public_project_in_list(client):
    pid = _public(client)
    assert pid in [p["id"] for p in client.get("/api/projects", headers=OTHER).json()]


def test_stranger_does_not_see_private_project(client):
    pid = _private(client)
    assert pid not in [p["id"] for p in client.get("/api/projects", headers=OTHER).json()]
    assert client.get(f"/api/projects/{pid}", headers=OTHER).status_code == 404


def test_stranger_can_edit_maps_of_a_public_project(client, cottage_source):
    pid = _public(client)
    r = client.post(f"/api/projects/{pid}/maps", json={"name": "M", "source": cottage_source},
                    headers=OTHER)
    assert r.status_code == 201
    mid = r.json()["id"]
    assert client.put(f"/api/maps/{mid}", json={"source": cottage_source}, headers=OTHER).status_code == 200
    assert client.get(f"/api/maps/{mid}/render", headers=OTHER).status_code == 200


def test_stranger_gets_403_on_owner_only_actions_of_a_public_project(client):
    pid = _public(client)
    assert client.delete(f"/api/projects/{pid}", headers=OTHER).status_code == 403
    assert client.post(f"/api/projects/{pid}/members", json={"identifier": "dev-user"},
                       headers=OTHER).status_code == 403


def test_stranger_cannot_link_a_campaign_to_a_public_project(client):
    pid = _public(client)
    r = client.post("/campaigns/their-game/link", json={"project_id": pid}, headers=OTHER)
    assert r.status_code == 404


@pytest.fixture
def stranger(client, monkeypatch):
    """A third, ordinary user. `dev-service` can't play the stranger here:
    linking a campaign makes the service a member (grant_service_access)."""
    from dungml_backend import deps
    from dungml_backend.identity import Principal, StaticIdentityProvider

    base = StaticIdentityProvider()
    tokens = dict(base._tokens)
    tokens["stranger"] = Principal("stranger", "stranger@dungml.local", (), False)
    monkeypatch.setattr(deps, "get_identity_provider", lambda: StaticIdentityProvider(tokens))
    return {"Authorization": "Bearer stranger"}


def test_stranger_cannot_unlink_from_a_public_project(client, stranger):
    pid = _public(client)
    assert client.post("/campaigns/g1/link", json={"project_id": pid}, headers=OWNER).status_code == 200
    assert client.delete("/campaigns/g1/link", headers=stranger).status_code == 404
    s = db.get_sessionmaker()()
    assert s.get(models.CampaignLink, "g1") is not None


def test_campaign_routes_stay_bounded_to_the_linked_project(client, cottage_source):
    linked = _public(client, "Linked")
    other = _public(client, "Other")
    other_map = client.post(f"/api/projects/{other}/maps",
                            json={"name": "M", "source": cottage_source}, headers=OWNER).json()["id"]
    assert client.post("/campaigns/g1/link", json={"project_id": linked}, headers=OWNER).status_code == 200
    # public, so the service can read it through /api like anyone …
    assert client.get(f"/api/maps/{other_map}", headers=OTHER).status_code == 200
    # … but the campaign-scoped routes only reach the linked project
    assert client.get(f"/campaigns/g1/maps/{other_map}/known", headers=OTHER).status_code == 404


# ---- Task 3: API ----


def _get(client, pid, h):
    return client.get(f"/api/projects/{pid}", headers=h).json()


def test_role_and_is_public_per_caller(client):
    pid = _public(client)
    mine = _get(client, pid, OWNER)
    assert (mine["role"], mine["is_public"], mine["shared"]) == ("owner", True, False)
    theirs = _get(client, pid, OTHER)
    assert (theirs["role"], theirs["shared"]) == ("public", True)


def test_member_role_on_a_public_project(client):
    pid = _public(client)
    client.get("/api/projects", headers=OTHER)   # provision the second user
    assert client.post(f"/api/projects/{pid}/members",
                       json={"identifier": "@dungeon-daemon-service"}, headers=OWNER).status_code == 201
    assert _get(client, pid, OTHER)["role"] == "member"


def test_list_has_no_duplicates_and_the_strongest_role(client):
    pid = _public(client)
    client.get("/api/projects", headers=OTHER)
    client.post(f"/api/projects/{pid}/members",
                json={"identifier": "@dungeon-daemon-service"}, headers=OWNER)
    rows = [p for p in client.get("/api/projects", headers=OTHER).json() if p["id"] == pid]
    assert len(rows) == 1 and rows[0]["role"] == "member"
    rows = [p for p in client.get("/api/projects", headers=OWNER).json() if p["id"] == pid]
    assert len(rows) == 1 and rows[0]["role"] == "owner"


def test_owner_makes_private_member_keeps_stranger_loses(client):
    pid = _public(client)
    r = client.patch(f"/api/projects/{pid}", json={"is_public": False}, headers=OWNER)
    assert r.status_code == 200 and r.json()["is_public"] is False
    assert client.get(f"/api/projects/{pid}", headers=OTHER).status_code == 404
    client.post(f"/api/projects/{pid}/members",
                json={"identifier": "@dungeon-daemon-service"}, headers=OWNER)
    assert _get(client, pid, OTHER)["role"] == "member"


def test_only_the_owner_changes_visibility(client):
    pid = _public(client)
    r = client.patch(f"/api/projects/{pid}", json={"is_public": False}, headers=OTHER)
    assert r.status_code == 403
    assert _get(client, pid, OWNER)["is_public"] is True


def test_anyone_with_access_can_still_rename(client):
    pid = _public(client)
    r = client.patch(f"/api/projects/{pid}", json={"name": "Renamed"}, headers=OTHER)
    assert r.status_code == 200 and r.json()["name"] == "Renamed"


def test_patch_needs_a_field(client):
    pid = _public(client)
    assert client.patch(f"/api/projects/{pid}", json={}, headers=OWNER).status_code == 422
