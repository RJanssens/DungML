"""Maps CRUD: nested-create + flat read/update/delete + ownership."""
from __future__ import annotations

import pytest


@pytest.fixture
def project_id(auth_client) -> str:
    return auth_client.post("/api/projects", json={"name": "P"}).json()["id"]


def test_list_maps_requires_owned_project(auth_client):
    r = auth_client.get("/api/projects/no-such/maps")
    assert r.status_code == 404


def test_create_map_returns_source(auth_client, project_id, cottage_source):
    r = auth_client.post(
        f"/api/projects/{project_id}/maps",
        json={"name": "Cottage", "source": cottage_source},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Cottage"
    assert body["source"] == cottage_source
    assert body["project_id"] == project_id


def test_list_maps_summary_does_not_include_source(
    auth_client, project_id, cottage_source,
):
    auth_client.post(
        f"/api/projects/{project_id}/maps",
        json={"name": "C", "source": cottage_source},
    )
    r = auth_client.get(f"/api/projects/{project_id}/maps")
    items = r.json()
    # The project is seeded with an editable core.dmap, so the map we
    # created is one of (at least) two entries.
    created = [it for it in items if it["name"] == "C"]
    assert len(created) == 1
    assert all("source" not in it for it in items)


def test_get_map_includes_source(auth_client, project_id, cottage_source):
    mid = auth_client.post(
        f"/api/projects/{project_id}/maps",
        json={"name": "C", "source": cottage_source},
    ).json()["id"]
    r = auth_client.get(f"/api/maps/{mid}")
    assert r.status_code == 200
    assert r.json()["source"] == cottage_source


def test_update_map_source_and_name(auth_client, project_id):
    mid = auth_client.post(
        f"/api/projects/{project_id}/maps", json={"name": "n", "source": ""},
    ).json()["id"]
    r = auth_client.put(
        f"/api/maps/{mid}", json={"name": "renamed", "source": "x"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"
    assert r.json()["source"] == "x"


def test_partial_update_keeps_other_fields(auth_client, project_id):
    mid = auth_client.post(
        f"/api/projects/{project_id}/maps",
        json={"name": "name", "source": "src"},
    ).json()["id"]
    r = auth_client.put(f"/api/maps/{mid}", json={"name": "new-name"})
    assert r.status_code == 200
    assert r.json()["source"] == "src"


def test_delete_map(auth_client, project_id):
    mid = auth_client.post(
        f"/api/projects/{project_id}/maps", json={"name": "x", "source": ""},
    ).json()["id"]
    assert auth_client.delete(f"/api/maps/{mid}").status_code == 204
    assert auth_client.get(f"/api/maps/{mid}").status_code == 404


def test_cross_user_map_access_is_404(client, cottage_source):
    a = client.post(
        "/api/auth/register", json={"email": "a@x.com", "password": "longenough"}
    ).json()
    ha = {"Authorization": f"Bearer {a['token']}"}
    pid = client.post("/api/projects", json={"name": "P"}, headers=ha).json()["id"]
    mid = client.post(
        f"/api/projects/{pid}/maps",
        json={"name": "m", "source": cottage_source},
        headers=ha,
    ).json()["id"]

    b = client.post(
        "/api/auth/register", json={"email": "b@x.com", "password": "longenough"}
    ).json()
    hb = {"Authorization": f"Bearer {b['token']}"}
    assert client.get(f"/api/maps/{mid}", headers=hb).status_code == 404
    assert client.put(
        f"/api/maps/{mid}", json={"source": "evil"}, headers=hb,
    ).status_code == 404
    assert client.delete(f"/api/maps/{mid}", headers=hb).status_code == 404
