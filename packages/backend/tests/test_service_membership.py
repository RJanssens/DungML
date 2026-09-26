"""Linking a campaign gives the campaign daemon access to that project.

The service token already authenticates as an ordinary user on `/api` — it
just had no *authorization* anywhere except its own hidden project, so
ttrpg2 could drive fog through the contract routes but couldn't read or add
a map through the normal API. Linking now grants membership; unlinking takes
it away.
"""
from __future__ import annotations

OWNER = {"Authorization": "Bearer dev-user"}
SVC = {"Authorization": "Bearer dev-service"}


def _project_with_map(client, cottage_source: str, name="Stonehell"):
    pid = client.post("/api/projects", json={"name": name, "is_public": False}, headers=OWNER).json()["id"]
    mid = client.post(
        f"/api/projects/{pid}/maps",
        json={"name": "Gatehouse", "source": cottage_source},
        headers=OWNER,
    ).json()["id"]
    return pid, mid


def _link(client, ext: str, pid: str, headers=OWNER):
    return client.post(f"/campaigns/{ext}/link", json={"project_id": pid}, headers=headers)


def test_service_cannot_reach_an_unlinked_project(client, cottage_source):
    _pid, mid = _project_with_map(client, cottage_source)
    assert client.get(f"/api/maps/{mid}", headers=SVC).status_code == 404


def test_linking_lets_the_service_read_the_projects_maps(client, cottage_source):
    pid, mid = _project_with_map(client, cottage_source)
    _link(client, "camp-1", pid)
    assert client.get(f"/api/maps/{mid}", headers=SVC).status_code == 200


def test_linking_lets_the_service_add_a_map_of_its_own(client, cottage_source):
    pid, _mid = _project_with_map(client, cottage_source)
    _link(client, "camp-1", pid)
    r = client.post(
        f"/api/projects/{pid}/maps",
        json={"name": "Ad-hoc fight", "source": ""},
        headers=SVC,
    )
    assert r.status_code == 201
    # And the GM sees it in their own project.
    names = [m["name"] for m in client.get(f"/api/projects/{pid}/maps", headers=OWNER).json()]
    assert "Ad-hoc fight" in names


def test_the_service_shows_up_as_a_member(client, cottage_source):
    pid, _mid = _project_with_map(client, cottage_source)
    _link(client, "camp-1", pid)
    subjects = [m["subject"] for m in client.get(f"/api/projects/{pid}/members", headers=OWNER).json()]
    assert "@dungeon-daemon-service" in subjects


def test_unlinking_revokes_the_access(client, cottage_source):
    pid, mid = _project_with_map(client, cottage_source)
    _link(client, "camp-1", pid)
    assert client.delete("/campaigns/camp-1/link", headers=OWNER).status_code == 204
    assert client.get(f"/api/maps/{mid}", headers=SVC).status_code == 404


def test_unlinking_one_campaign_keeps_access_for_another(client, cottage_source):
    """Two campaigns on one project is the normal case here — revoking on the
    first unlink would break the second campaign's map access."""
    pid, mid = _project_with_map(client, cottage_source)
    _link(client, "camp-1", pid)
    _link(client, "camp-2", pid)
    client.delete("/campaigns/camp-1/link", headers=OWNER)
    assert client.get(f"/api/maps/{mid}", headers=SVC).status_code == 200


def test_relinking_to_another_project_moves_the_access(client, cottage_source):
    pid_a, mid_a = _project_with_map(client, cottage_source, name="First")
    pid_b, mid_b = _project_with_map(client, cottage_source, name="Second")
    _link(client, "camp-1", pid_a)
    _link(client, "camp-1", pid_b)

    assert client.get(f"/api/maps/{mid_b}", headers=SVC).status_code == 200
    assert client.get(f"/api/maps/{mid_a}", headers=SVC).status_code == 404


def test_the_service_still_cannot_delete_the_project(client, cottage_source):
    pid, _mid = _project_with_map(client, cottage_source)
    _link(client, "camp-1", pid)
    assert client.delete(f"/api/projects/{pid}", headers=SVC).status_code == 403
