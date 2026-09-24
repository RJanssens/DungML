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
    assert r.status_code == 404


def test_play_routes_guard_unlinked_and_stray_maps(client):
    _, mid = _linked_map(client)
    # Unknown map under a linked campaign → 404.
    assert client.get("/campaigns/inst-1/maps/00000000-0000-0000-0000-000000000000/info",
                      headers=SVC).status_code == 404
    # tokens/reveal/info require service.
    assert client.get(f"/campaigns/inst-1/maps/{mid}/info", headers=HUMAN).status_code == 403


def test_campaign_maps_report_is_default(client):
    # A project with one renderable map: it is the auto-default.
    pid = client.post("/api/projects", json={"name": "P"}, headers=HUMAN).json()["id"]
    mid = client.post(
        f"/api/projects/{pid}/maps",
        json={"name": "A", "source": 'map "A" { grid { bounds 5 x 5 } }'},
        headers=HUMAN,
    ).json()["id"]
    client.post("/campaigns/inst-9/link", json={"project_id": pid}, headers=HUMAN)
    entries = client.get("/campaigns/inst-9/maps", headers=SVC).json()
    entry = next(e for e in entries if e["id"] == mid)
    assert entry["is_default"] is True


def _project_with_source(client, source, name="Keep"):
    pid = client.post("/api/projects", json={"name": name}, headers=HUMAN).json()["id"]
    mid = client.post(f"/api/projects/{pid}/maps",
                      json={"name": "L1", "source": source}, headers=HUMAN).json()["id"]
    return pid, mid


def test_map_rooms_returns_nodes_with_exits(client, crypt_source):
    _, mid = _project_with_source(client, crypt_source)
    r = client.get(f"/maps/{mid}/rooms", headers=SVC)
    assert r.status_code == 200
    rooms = r.json()["rooms"]
    assert rooms, "expected nodes from a real multi-room map"
    for room in rooms:
        assert set(room) == {"id", "name", "kind", "label", "hidden", "exits", "secret_exits"}
        assert room["id"].startswith(("room.", "corridor."))
        assert isinstance(room["exits"], list)
    # connectivity is present: at least one node has an exit
    assert any(room["exits"] for room in rooms)


def test_map_rooms_unknown_map_404(client):
    assert client.get("/maps/does-not-exist/rooms", headers=SVC).status_code == 404


def test_map_rooms_requires_service(client, crypt_source):
    _, mid = _project_with_source(client, crypt_source)
    assert client.get(f"/maps/{mid}/rooms", headers=HUMAN).status_code == 403


def test_party_sets_location_and_reveals(client, crypt_source):
    pid, mid = _project_with_source(client, crypt_source)
    client.post("/campaigns/inst-1/link", json={"project_id": pid}, headers=HUMAN)
    room_id = client.get(f"/maps/{mid}/rooms", headers=SVC).json()["rooms"][0]["id"]

    r = client.post(f"/campaigns/inst-1/maps/{mid}/party",
                    json={"room_id": room_id}, headers=SVC)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["party_location"] == room_id

    db = get_sessionmaker()()
    try:
        s = db.query(models.PlaySession).filter_by(map_id=mid, external_id="inst-1").one()
        assert s.party_location == room_id
        assert room_id in (s.discovered_nodes or [])
    finally:
        db.close()


def test_party_requires_service(client, crypt_source):
    pid, mid = _project_with_source(client, crypt_source)
    client.post("/campaigns/inst-1/link", json={"project_id": pid}, headers=HUMAN)
    assert client.post(f"/campaigns/inst-1/maps/{mid}/party",
                       json={"room_id": "room.x"}, headers=HUMAN).status_code == 403


KEYED = '''map "K" { grid { bounds 30 x 12 } }
room "hall" { rect 0,0 10 x 10 label "39" description "A vaulted hall." dm_notes "Ghouls below." }
room "cave_2" { rect 20,0 6 x 6 label "37" }
room "vault" { rect 12,0 4 x 4 label "Vault" }
corridor "c1" { width 1 segment line from 10,5 to 20,3 }
door at 10,5 { connects room.hall, corridor.c1 type wooden }
door at 20,3 { connects corridor.c1, room.cave_2 type iron state locked }
door at 12,2 { connects room.vault, room.hall type secret }
'''


def _keyed(client, ext="inst-1"):
    pid, mid = _project_with_source(client, KEYED)
    client.post(f"/campaigns/{ext}/link", json={"project_id": pid}, headers=HUMAN)
    return pid, mid


def test_room_by_label_returns_both_halves(client):
    _, mid = _keyed(client)
    r = client.get(f"/campaigns/inst-1/maps/{mid}/rooms/39", headers=SVC)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "room.hall"
    assert body["perceived"]["description"] == "A vaulted hall."
    assert body["dm_only"]["notes"] == "Ghouls below."


def test_room_fog_scope_drops_dm_only(client):
    _, mid = _keyed(client)
    body = client.get(f"/campaigns/inst-1/maps/{mid}/rooms/39",
                      params={"scope": "fog"}, headers=SVC).json()
    assert "dm_only" not in body


def test_room_unknown_404_lists_candidates(client):
    _, mid = _keyed(client)
    r = client.get(f"/campaigns/inst-1/maps/{mid}/rooms/nowhere", headers=SVC)
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "unknown room"


def test_room_on_unparseable_map_is_409(client):
    pid, mid = _project_with_source(client, 'map "X" { grid { bounds 5 x 5 } } room "a" {')
    client.post("/campaigns/inst-1/link", json={"project_id": pid}, headers=HUMAN)
    assert client.get(f"/campaigns/inst-1/maps/{mid}/rooms/a", headers=SVC).status_code == 409


def test_party_by_label_returns_the_room(client):
    _, mid = _keyed(client)
    r = client.post(f"/campaigns/inst-1/maps/{mid}/party", json={"room_id": "37"}, headers=SVC)
    assert r.status_code == 200
    body = r.json()
    assert body["party_location"] == "room.cave_2"
    assert body["room"]["label"] == "37" and body["room"]["party_here"] is True


def test_party_unknown_room_is_404_and_moves_nothing(client):
    _, mid = _keyed(client)
    r = client.post(f"/campaigns/inst-1/maps/{mid}/party",
                    json={"room_id": "room.nope"}, headers=SVC)
    assert r.status_code == 404
    db = get_sessionmaker()()
    try:
        rows = db.query(models.PlaySession).filter_by(map_id=mid, external_id="inst-1").all()
        assert all(s.party_location is None for s in rows)
    finally:
        db.close()


def test_party_clears_marker_on_the_campaigns_other_maps(client):
    pid, mid = _keyed(client)
    mid2 = client.post(f"/api/projects/{pid}/maps",
                       json={"name": "L2", "source": KEYED}, headers=HUMAN).json()["id"]
    client.post(f"/campaigns/inst-1/maps/{mid}/party", json={"room_id": "39"}, headers=SVC)
    client.post(f"/campaigns/inst-1/maps/{mid2}/party", json={"room_id": "37"}, headers=SVC)
    db = get_sessionmaker()()
    try:
        s1 = db.query(models.PlaySession).filter_by(map_id=mid, external_id="inst-1").one()
        s2 = db.query(models.PlaySession).filter_by(map_id=mid2, external_id="inst-1").one()
        assert s1.party_location is None and s2.party_location == "room.cave_2"
        link = db.get(models.CampaignLink, "inst-1")
        assert link.active_map_id == mid2
    finally:
        db.close()


def test_reveal_unknown_is_404(client):
    _, mid = _keyed(client)
    r = client.post(f"/campaigns/inst-1/maps/{mid}/reveal",
                    json={"feature_id": "room.nope"}, headers=SVC)
    assert r.status_code == 404


def test_reveal_returns_room(client):
    _, mid = _keyed(client)
    r = client.post(f"/campaigns/inst-1/maps/{mid}/reveal",
                    json={"feature_id": "37"}, headers=SVC)
    assert r.status_code == 200 and r.json()["revealed"] == "room.cave_2"


def test_doors_marks_secret_found_and_state(client):
    _, mid = _keyed(client)
    r = client.post(f"/campaigns/inst-1/maps/{mid}/doors",
                    json={"between": ["room.hall", "room.vault"]}, headers=SVC)
    assert r.status_code == 200 and r.json()["door"] == "12,2"
    room = client.get(f"/campaigns/inst-1/maps/{mid}/rooms/39", headers=SVC).json()
    assert "12,2" in {e["door"] for e in room["perceived"]["exits"]}
    r = client.post(f"/campaigns/inst-1/maps/{mid}/doors",
                    json={"door": "20,3", "state": "open"}, headers=SVC)
    assert r.json()["state"] == "open"


def test_doors_unknown_is_404(client):
    _, mid = _keyed(client)
    assert client.post(f"/campaigns/inst-1/maps/{mid}/doors",
                       json={"door": "99,99"}, headers=SVC).status_code == 404


def test_known_map_after_moves(client):
    _, mid = _keyed(client)
    client.post(f"/campaigns/inst-1/maps/{mid}/party", json={"room_id": "39"}, headers=SVC)
    km = client.get(f"/campaigns/inst-1/maps/{mid}/known", headers=SVC).json()
    assert km["party_location"] == "room.hall"
    assert km["frontier"][0]["leads_to"] == "corridor.c1"


def test_map_rooms_hides_secret_exits_and_carries_labels(client):
    _, mid = _keyed(client)
    rooms = {r["id"]: r for r in client.get(f"/maps/{mid}/rooms", headers=SVC).json()["rooms"]}
    assert rooms["room.hall"]["label"] == "39"
    assert "room.vault" not in rooms["room.hall"]["exits"]
    assert rooms["room.hall"]["secret_exits"] == ["room.vault"]
