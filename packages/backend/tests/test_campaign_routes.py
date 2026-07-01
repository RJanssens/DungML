"""The /campaigns/{external_id}/… contract (sub-project B)."""
SVC = {"Authorization": "Bearer dev-service"}
HUMAN = {"Authorization": "Bearer dev-user"}

ROOM = 'map "M" {\n  grid { bounds 20 x 20 }\n}\n\nroom "hall" {\n  rect 0,0 8 x 8\n}\n'


def _project_with_map(client, name="Keep"):
    pid = client.post("/api/projects", json={"name": name}, headers=HUMAN).json()["id"]
    mid = client.post(f"/api/projects/{pid}/maps",
                      json={"name": "L1", "source": ROOM}, headers=HUMAN).json()["id"]
    return pid, mid


def test_link_requires_ownership(client):
    # dev-user owns this project; a link succeeds.
    pid, _ = _project_with_map(client)
    r = client.post("/campaigns/inst-1/link", json={"project_id": pid}, headers=HUMAN)
    assert r.status_code == 200 and r.json() == {"external_id": "inst-1", "project_id": pid}


def test_link_unknown_project_404(client):
    r = client.post("/campaigns/inst-1/link",
                    json={"project_id": "00000000-0000-0000-0000-000000000000"},
                    headers=HUMAN)
    assert r.status_code == 404


def test_link_requires_user_token_not_service(client):
    pid, _ = _project_with_map(client)
    # A service principal is not a user and does not own the project → 404.
    r = client.post("/campaigns/inst-1/link", json={"project_id": pid}, headers=SVC)
    assert r.status_code == 404


def test_list_maps_service_only_renderable(client):
    pid, mid = _project_with_map(client)
    client.post("/campaigns/inst-1/link", json={"project_id": pid}, headers=HUMAN)
    r = client.get("/campaigns/inst-1/maps", headers=SVC)
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()]
    assert mid in ids
    # The seeded core.dmap is a library (include-only) and must be filtered out.
    assert all(m["name"] != "core.dmap" for m in r.json())


def test_list_maps_unlinked_404(client):
    assert client.get("/campaigns/nope/maps", headers=SVC).status_code == 404


def test_list_maps_requires_service(client):
    pid, _ = _project_with_map(client)
    client.post("/campaigns/inst-1/link", json={"project_id": pid}, headers=HUMAN)
    assert client.get("/campaigns/inst-1/maps", headers=HUMAN).status_code == 403


def test_unlink_idempotent(client):
    pid, _ = _project_with_map(client)
    client.post("/campaigns/inst-1/link", json={"project_id": pid}, headers=HUMAN)
    assert client.delete("/campaigns/inst-1/link", headers=HUMAN).status_code == 204
    assert client.delete("/campaigns/inst-1/link", headers=HUMAN).status_code == 204  # already gone
    assert client.get("/campaigns/inst-1/maps", headers=SVC).status_code == 404
