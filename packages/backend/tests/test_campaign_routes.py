"""The /campaigns/{external_id}/… contract (sub-project B)."""
from dungml_backend import models
from dungml_backend.db import get_sessionmaker

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


def test_link_cannot_hijack_existing_link_from_other_user(client):
    # A different, non-dev user already has "inst-1" linked to their own project.
    db = get_sessionmaker()()
    other_user = models.User(subject="other-gm", email="other-gm@t.local")
    db.add(other_user); db.flush()
    other_project = models.Project(user_id=other_user.id, name="Other Keep")
    db.add(other_project); db.flush()
    other_map = models.Map(project_id=other_project.id, name="OtherL1", source=ROOM)
    db.add(other_map); db.flush()
    db.add(models.CampaignLink(
        external_id="inst-1", project_id=other_project.id, user_id=other_user.id
    ))
    db.commit()

    # dev-user owns their own project and tries to hijack the existing link.
    pid, _ = _project_with_map(client, name="Mine")
    r = client.post("/campaigns/inst-1/link", json={"project_id": pid}, headers=HUMAN)
    assert r.status_code == 404

    # The original link must be unchanged: /maps still resolves to the other
    # user's project (its map, not dev-user's).
    r2 = client.get("/campaigns/inst-1/maps", headers=SVC)
    assert r2.status_code == 200
    ids = [m["id"] for m in r2.json()]
    assert other_map.id in ids


def _linked_map(client):
    pid, mid = _project_with_map(client)
    client.post("/campaigns/inst-1/link", json={"project_id": pid}, headers=HUMAN)
    return pid, mid


def test_token_and_render_roundtrip(client):
    _, mid = _linked_map(client)
    tok = client.post(f"/campaigns/inst-1/maps/{mid}/tokens",
                      json={"scope": "fog"}, headers=SVC).json()["token"]
    r = client.get(f"/campaigns/inst-1/maps/{mid}/render", params={"token": tok})
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg")


def test_token_is_map_scoped(client):
    pid, mid = _linked_map(client)
    mid2 = client.post(f"/api/projects/{pid}/maps",
                       json={"name": "L2", "source": ROOM}, headers=HUMAN).json()["id"]
    tok = client.post(f"/campaigns/inst-1/maps/{mid}/tokens",
                      json={"scope": "fog"}, headers=SVC).json()["token"]
    # A token minted for mid must not render mid2.
    r = client.get(f"/campaigns/inst-1/maps/{mid2}/render", params={"token": tok})
    assert r.status_code == 401


def test_render_rejects_bad_token(client):
    _, mid = _linked_map(client)
    r = client.get(f"/campaigns/inst-1/maps/{mid}/render", params={"token": "garbage"})
    assert r.status_code == 401


def test_reveal_is_per_campaign_and_never_mutates_source(client):
    pid, mid = _project_with_map(client)
    for inst in ("inst-a", "inst-b"):
        client.post(f"/campaigns/{inst}/link", json={"project_id": pid}, headers=HUMAN)
    # Reveal a known node for inst-a only.
    r = client.post(f"/campaigns/inst-a/maps/{mid}/reveal",
                    json={"feature_id": "room.hall"}, headers=SVC)
    assert r.status_code == 200 and r.json()["ok"] is True
    # inst-a and inst-b resolve to different sessions (distinct fog).
    ia = client.get(f"/campaigns/inst-a/maps/{mid}/info", headers=SVC).json()
    ib = client.get(f"/campaigns/inst-b/maps/{mid}/info", headers=SVC).json()
    assert ia["map_id"] == ib["map_id"] == mid
    assert ia["session_id"] != ib["session_id"]
    # Authored source is untouched by play.
    src = client.get(f"/api/maps/{mid}", headers=HUMAN).json()["source"]
    assert src == ROOM


def test_reveal_noops_unknown_feature(client):
    _, mid = _linked_map(client)
    r = client.post(f"/campaigns/inst-1/maps/{mid}/reveal",
                    json={"feature_id": "room.nope"}, headers=SVC)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_play_routes_guard_unlinked_and_stray_maps(client):
    _, mid = _linked_map(client)
    # Unknown map under a linked campaign → 404.
    assert client.get("/campaigns/inst-1/maps/00000000-0000-0000-0000-000000000000/info",
                      headers=SVC).status_code == 404
    # tokens/reveal/info require service.
    assert client.get(f"/campaigns/inst-1/maps/{mid}/info", headers=HUMAN).status_code == 403
