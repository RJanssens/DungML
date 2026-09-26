"""Project membership — more than one user on a project.

A project has one owner (`projects.user_id`) plus any number of members.
Members get everything the owner gets except deleting the project and
managing its membership.

Following the convention in test_projects.py, the `dev-service` static token
stands in for "a second principal" — the static identity provider only ships
two tokens.
"""
from __future__ import annotations

OWNER = {"Authorization": "Bearer dev-user"}
OTHER = {"Authorization": "Bearer dev-service"}
OTHER_SUBJECT = "@dungeon-daemon-service"
OTHER_EMAIL = "service@dungml.local"


def _provision_other(client) -> None:
    """Touch a CurrentUser route as the second principal so its User row exists.

    `POST /members` deliberately refuses identifiers with no user row, so the
    row has to be there first.
    """
    assert client.get("/api/projects", headers=OTHER).status_code == 200


def _project(client, name: str = "Shared") -> str:
    return client.post("/api/projects", json={"name": name, "is_public": False}, headers=OWNER).json()["id"]


def test_member_sees_shared_project_in_list(client):
    pid = _project(client)
    _provision_other(client)
    r = client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )
    assert r.status_code == 201

    items = client.get("/api/projects", headers=OTHER).json()
    assert [p["id"] for p in items] == [pid]
    assert items[0]["shared"] is True


def test_owner_list_does_not_mark_own_project_shared(client):
    _project(client)
    items = client.get("/api/projects", headers=OWNER).json()
    assert items[0]["shared"] is False


def test_member_can_read_the_project_and_its_maps(client):
    pid = _project(client)
    _provision_other(client)
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )

    assert client.get(f"/api/projects/{pid}", headers=OTHER).status_code == 200
    assert client.get(f"/api/projects/{pid}/maps", headers=OTHER).status_code == 200


def test_member_can_read_a_map_of_the_shared_project(client, cottage_source):
    pid = _project(client)
    mid = client.post(
        f"/api/projects/{pid}/maps",
        json={"name": "Cottage", "source": cottage_source},
        headers=OWNER,
    ).json()["id"]
    _provision_other(client)
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )

    r = client.get(f"/api/maps/{mid}", headers=OTHER)
    assert r.status_code == 200
    assert r.json()["id"] == mid


def test_member_can_run_a_play_session_on_a_shared_map(client, cottage_source):
    pid = _project(client)
    mid = client.post(
        f"/api/projects/{pid}/maps",
        json={"name": "Cottage", "source": cottage_source},
        headers=OWNER,
    ).json()["id"]
    _provision_other(client)
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )

    r = client.post(
        f"/api/maps/{mid}/sessions", json={"name": "Party"}, headers=OTHER
    )
    assert r.status_code == 201
    assert client.get(f"/api/maps/{mid}/sessions", headers=OTHER).status_code == 200


def test_add_member_by_email(client):
    pid = _project(client)
    _provision_other(client)
    r = client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_EMAIL}, headers=OWNER
    )
    assert r.status_code == 201
    assert client.get(f"/api/projects/{pid}", headers=OTHER).status_code == 200


def test_add_member_rejects_a_user_who_has_never_signed_in(client):
    pid = _project(client)
    r = client.post(
        f"/api/projects/{pid}/members",
        json={"identifier": "nobody@example.com"},
        headers=OWNER,
    )
    assert r.status_code == 404


def test_adding_the_same_member_twice_is_idempotent(client):
    pid = _project(client)
    _provision_other(client)
    body = {"identifier": OTHER_SUBJECT}
    assert client.post(f"/api/projects/{pid}/members", json=body, headers=OWNER).status_code == 201
    assert client.post(f"/api/projects/{pid}/members", json=body, headers=OWNER).status_code == 201
    assert len(client.get(f"/api/projects/{pid}/members", headers=OWNER).json()) == 1


def test_members_list_is_visible_to_a_member(client):
    pid = _project(client)
    _provision_other(client)
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )
    rows = client.get(f"/api/projects/{pid}/members", headers=OTHER).json()
    assert [r["subject"] for r in rows] == [OTHER_SUBJECT]


def test_member_cannot_add_or_remove_members(client):
    pid = _project(client)
    _provision_other(client)
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )
    uid = client.get(f"/api/projects/{pid}/members", headers=OWNER).json()[0]["user_id"]

    assert client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OTHER
    ).status_code == 403
    assert client.delete(
        f"/api/projects/{pid}/members/{uid}", headers=OTHER
    ).status_code == 403


def test_member_cannot_delete_the_project(client):
    pid = _project(client)
    _provision_other(client)
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )
    assert client.delete(f"/api/projects/{pid}", headers=OTHER).status_code == 403
    assert client.get(f"/api/projects/{pid}", headers=OWNER).status_code == 200


def test_removing_a_member_revokes_access(client):
    pid = _project(client)
    _provision_other(client)
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )
    uid = client.get(f"/api/projects/{pid}/members", headers=OWNER).json()[0]["user_id"]

    assert client.delete(f"/api/projects/{pid}/members/{uid}", headers=OWNER).status_code == 204
    assert client.get(f"/api/projects/{pid}", headers=OTHER).status_code == 404
    assert client.get("/api/projects", headers=OTHER).json() == []


def test_non_member_still_gets_404_on_the_members_list(client):
    pid = _project(client)
    _provision_other(client)
    assert client.get(f"/api/projects/{pid}/members", headers=OTHER).status_code == 404


# ---- the campaign contract (root-mounted, not under /api) ----


def test_member_can_link_a_campaign_to_the_shared_project(client):
    pid = _project(client)
    _provision_other(client)
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )
    r = client.post("/campaigns/camp-1/link", json={"project_id": pid}, headers=OTHER)
    assert r.status_code == 200
    assert r.json()["project_id"] == pid


def test_member_can_unlink_a_campaign_the_owner_linked(client):
    pid = _project(client)
    _provision_other(client)
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )
    client.post("/campaigns/camp-1/link", json={"project_id": pid}, headers=OWNER)
    assert client.delete("/campaigns/camp-1/link", headers=OTHER).status_code == 204


def test_member_can_relink_a_campaign_the_owner_linked(client):
    """The old rule compared the link's recorded user to the caller, which
    would lock a member out of a campaign the owner linked."""
    pid = _project(client)
    _provision_other(client)
    client.post(
        f"/api/projects/{pid}/members", json={"identifier": OTHER_SUBJECT}, headers=OWNER
    )
    client.post("/campaigns/camp-1/link", json={"project_id": pid}, headers=OWNER)
    r = client.post("/campaigns/camp-1/link", json={"project_id": pid}, headers=OTHER)
    assert r.status_code == 200


def test_outsider_cannot_link_a_campaign_to_someone_elses_project(client):
    pid = _project(client)
    _provision_other(client)
    r = client.post("/campaigns/camp-1/link", json={"project_id": pid}, headers=OTHER)
    assert r.status_code == 404
