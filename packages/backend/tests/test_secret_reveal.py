"""The DM reveals a secret (a trap, a hidden inscription, …) to the players.

A play session keeps a reveal list of secret keys (see dungml.secrets); the
players' fogged view hides every secret not on it. Revealing lives on the
session — the authored map never changes.
"""
from sqlalchemy import inspect, text

from dungml_backend import db as backend_db

SVC = {"Authorization": "Bearer dev-service"}
HUMAN = {"Authorization": "Bearer dev-user"}

TRAPPED = """include "core.dmap"
map "M" { grid { bounds 20 x 20 } }
room "hall" {
  rect 0,0 10 x 10
  feature pit-trap at 3,3 id pit_1
  text "Beware" at 5,8 secret
}
"""


def _linked_map(client, source=TRAPPED):
    pid = client.post("/api/projects", json={"name": "Keep"}, headers=HUMAN).json()["id"]
    mid = client.post(f"/api/projects/{pid}/maps",
                      json={"name": "L1", "source": source}, headers=HUMAN).json()["id"]
    client.post("/campaigns/inst-1/link", json={"project_id": pid}, headers=HUMAN)
    client.post(f"/campaigns/inst-1/maps/{mid}/party", json={"room_id": "hall"}, headers=SVC)
    return pid, mid


def _fog_svg(client, mid) -> str:
    tok = client.post(f"/campaigns/inst-1/maps/{mid}/tokens",
                      json={"scope": "fog"}, headers=SVC).json()["token"]
    return client.get(f"/campaigns/inst-1/maps/{mid}/render", params={"token": tok}).text


def _secrets(client, mid) -> dict:
    ctx = client.get(f"/campaigns/inst-1/maps/{mid}/rooms/hall", headers=SVC).json()
    return {s["key"]: s["revealed"] for s in ctx["dm_only"]["secrets"]}


# ---- campaigns contract ----

def test_reveal_shows_the_secret_to_the_players(client):
    _, mid = _linked_map(client)
    assert 'data-ref="pit-trap"' not in _fog_svg(client, mid)
    r = client.post(f"/campaigns/inst-1/maps/{mid}/secrets",
                    json={"key": "pit_1"}, headers=SVC)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "key": "pit_1", "kind": "feature",
                        "node": "room.hall", "revealed": True}
    assert 'data-ref="pit-trap"' in _fog_svg(client, mid)
    assert _secrets(client, mid) == {"pit_1": True, "room.hall/text@5,8": False}


def test_reveal_can_be_taken_back(client):
    _, mid = _linked_map(client)
    client.post(f"/campaigns/inst-1/maps/{mid}/secrets", json={"key": "pit_1"}, headers=SVC)
    r = client.post(f"/campaigns/inst-1/maps/{mid}/secrets",
                    json={"key": "pit_1", "revealed": False}, headers=SVC)
    assert r.json()["revealed"] is False
    assert 'data-ref="pit-trap"' not in _fog_svg(client, mid)


def test_unknown_secret_is_a_404_with_candidates(client):
    _, mid = _linked_map(client)
    r = client.post(f"/campaigns/inst-1/maps/{mid}/secrets",
                    json={"key": "pit_9"}, headers=SVC)
    assert r.status_code == 404
    body = r.json()["detail"]  # the contract's error envelope
    assert body["error"] == "unknown secret" and body["key"] == "pit_9"
    assert set(body["candidates"]) == {"pit_1", "room.hall/text@5,8"}


def test_reveal_on_an_unparseable_map_is_a_409(client):
    pid, mid = _linked_map(client)
    client.put(f"/api/maps/{mid}", json={"source": "map {"}, headers=HUMAN)
    r = client.post(f"/campaigns/inst-1/maps/{mid}/secrets",
                    json={"key": "pit_1"}, headers=SVC)
    assert r.status_code == 409


def test_reveal_requires_the_service(client):
    _, mid = _linked_map(client)
    r = client.post(f"/campaigns/inst-1/maps/{mid}/secrets",
                    json={"key": "pit_1"}, headers=HUMAN)
    assert r.status_code == 403


def test_reveals_are_per_campaign(client):
    pid, mid = _linked_map(client)
    client.post("/campaigns/inst-2/link", json={"project_id": pid}, headers=HUMAN)
    client.post(f"/campaigns/inst-1/maps/{mid}/secrets", json={"key": "pit_1"}, headers=SVC)
    ctx = client.get(f"/campaigns/inst-2/maps/{mid}/rooms/hall", headers=SVC).json()
    assert {s["key"]: s["revealed"] for s in ctx["dm_only"]["secrets"]}["pit_1"] is False


# ---- web play sessions ----

def test_session_reveal_route_and_render(client):
    pid = client.post("/api/projects", json={"name": "Keep"}, headers=HUMAN).json()["id"]
    mid = client.post(f"/api/projects/{pid}/maps",
                      json={"name": "L1", "source": TRAPPED}, headers=HUMAN).json()["id"]
    sid = client.post(f"/api/maps/{mid}/sessions",
                      json={"name": "Run", "start_location": "room.hall"},
                      headers=HUMAN).json()["id"]
    svg = client.get(f"/api/sessions/{sid}/render", headers=HUMAN).json()["svg"]
    assert "Beware" not in svg
    r = client.post(f"/api/sessions/{sid}/secrets",
                    json={"key": "room.hall/text@5,8"}, headers=HUMAN)
    assert r.status_code == 200 and r.json()["revealed"] is True
    assert r.json()["revealed_secrets"] == ["room.hall/text@5,8"]
    svg = client.get(f"/api/sessions/{sid}/render", headers=HUMAN).json()["svg"]
    assert "Beware" in svg
    assert client.post(f"/api/sessions/{sid}/secrets", json={"key": "nope"},
                       headers=HUMAN).status_code == 404


# ---- storage ----

def test_ensure_columns_restores_the_reveal_list_on_an_old_db(client):
    engine = backend_db.get_engine()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE play_sessions DROP COLUMN revealed_secrets"))
    assert "revealed_secrets" not in {c["name"] for c in inspect(engine).get_columns("play_sessions")}
    backend_db.ensure_columns()
    backend_db.ensure_columns()  # idempotent
    assert "revealed_secrets" in {c["name"] for c in inspect(engine).get_columns("play_sessions")}
