"""The map contract endpoints (root-mounted), via the service principal."""
SVC = {"Authorization": "Bearer dev-service"}
HUMAN = {"Authorization": "Bearer dev-user"}

# NOTE: The brief's single-line ROOM source used invalid grid syntax
# (`grid { width 20 height 20 }` and inline `rect 0,0 8 x 8`).
# Substituted with equivalent multi-line source that parses under dungml's grammar
# (`grid { bounds 20 x 20 }` and proper block formatting).
ROOM = 'map "M" {\n  grid { bounds 20 x 20 }\n}\n\nroom "hall" {\n  rect 0,0 8 x 8\n}\n'


def test_fragments_requires_service(client):
    assert client.post("/maps/i1/fragments", json={"dungml": ROOM}, headers=HUMAN).status_code == 403


def test_fragments_provisions_and_appends(client):
    r = client.post("/maps/i1/fragments", json={"dungml": ROOM, "name": "h"}, headers=SVC)
    assert r.status_code == 200 and r.json()["ok"] is True
    # second fragment appends
    frag = 'room "vault" {\n  rect 10,0 6 x 6\n}\n'
    assert client.post("/maps/i1/fragments", json={"dungml": frag}, headers=SVC).status_code == 200


def test_reveal_unknown_node_is_404(client):
    client.post("/maps/i2/fragments", json={"dungml": ROOM}, headers=SVC)
    r = client.post("/maps/i2/reveal", json={"feature_id": "room.does-not-exist"}, headers=SVC)
    assert r.status_code == 404


def test_reveal_marks_known_node(client):
    client.post("/maps/i3/fragments", json={"dungml": ROOM}, headers=SVC)
    r = client.post("/maps/i3/reveal", json={"feature_id": "room.hall"}, headers=SVC)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_tokens_mint(client):
    client.post("/maps/i4/fragments", json={"dungml": ROOM}, headers=SVC)
    r = client.post("/maps/i4/tokens", json={"scope": "fog"}, headers=SVC)
    assert r.status_code == 200 and r.json()["token"]


# ---------------------------------------------------------------------------
# PUT /source — replace, for a caller that owns its DSL and re-emits it whole
# ---------------------------------------------------------------------------

VAULT = 'map "M" {\n  grid { bounds 20 x 20 }\n}\n\nroom "vault" {\n  rect 10,0 6 x 6\n}\n'


def test_source_requires_service(client):
    assert client.put(
        "/maps/s1/source", json={"dungml": ROOM}, headers=HUMAN
    ).status_code == 403


def test_source_provisions_on_first_put(client):
    r = client.put("/maps/s2/source", json={"dungml": ROOM}, headers=SVC)
    assert r.status_code == 200 and r.json()["ok"] is True
    mid = client.get("/maps/s2/info", headers=SVC).json()["map_id"]
    rooms = {n["id"] for n in client.get(f"/maps/{mid}/rooms", headers=SVC).json()["rooms"]}
    assert rooms == {"room.hall"}


def test_source_replaces_rather_than_appends(client):
    client.put("/maps/s3/source", json={"dungml": ROOM}, headers=SVC)
    client.put("/maps/s3/source", json={"dungml": VAULT}, headers=SVC)
    mid = client.get("/maps/s3/info", headers=SVC).json()["map_id"]
    rooms = {n["id"] for n in client.get(f"/maps/{mid}/rooms", headers=SVC).json()["rooms"]}
    # The first source's room is gone, not stacked alongside the second's.
    assert rooms == {"room.vault"}


def test_source_preserves_discovery(client):
    """A redraw must not re-fog rooms the party already explored — node ids are
    stable, so the PlaySession overlay survives a source replacement."""
    client.put("/maps/s4/source", json={"dungml": ROOM}, headers=SVC)
    client.post("/maps/s4/reveal", json={"feature_id": "room.hall"}, headers=SVC)
    client.put("/maps/s4/source", json={"dungml": ROOM}, headers=SVC)
    tok = client.post("/maps/s4/tokens", json={"scope": "fog"}, headers=SVC).json()["token"]
    svg = client.get("/maps/s4/render", params={"token": tok}).text
    assert "map not ready" not in svg
    # room.hall still renders in the players' view after the replace.
    assert 'data-room="hall"' in svg


# ---------------------------------------------------------------------------
# POST /party — party marker on the legacy map contract
# ---------------------------------------------------------------------------

def test_party_requires_service(client):
    assert client.post(
        "/maps/p1/party", json={"room_id": "room.hall"}, headers=HUMAN
    ).status_code == 403


def test_party_unknown_node_is_404(client):
    client.put("/maps/p2/source", json={"dungml": ROOM}, headers=SVC)
    r = client.post("/maps/p2/party", json={"room_id": "room.nope"}, headers=SVC)
    assert r.status_code == 404


def test_party_unparseable_source_is_409(client):
    client.post("/maps/p3/fragments", json={"dungml": "not a map"}, headers=SVC)
    r = client.post("/maps/p3/party", json={"room_id": "room.hall"}, headers=SVC)
    assert r.status_code == 409


def test_party_marker_appears_in_render(client):
    client.put("/maps/p4/source", json={"dungml": ROOM}, headers=SVC)
    client.post("/maps/p4/party", json={"room_id": "room.hall"}, headers=SVC)
    tok = client.post("/maps/p4/tokens", json={"scope": "fog"}, headers=SVC).json()["token"]
    svg = client.get("/maps/p4/render", params={"token": tok}).text
    assert 'class="party-start"' in svg
    assert 'data-party-node="room.hall"' in svg


def test_party_reveals_the_node_it_moves_to(client):
    """Moving the party into a room discovers it — no separate /reveal needed."""
    client.put("/maps/p5/source", json={"dungml": ROOM}, headers=SVC)
    r = client.post("/maps/p5/party", json={"room_id": "room.hall"}, headers=SVC)
    assert r.json()["room"]["id"] == "room.hall"
    tok = client.post("/maps/p5/tokens", json={"scope": "fog"}, headers=SVC).json()["token"]
    svg = client.get("/maps/p5/render", params={"token": tok}).text
    assert 'data-room="hall"' in svg
