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


def test_reveal_noops_unknown_node(client):
    client.post("/maps/i2/fragments", json={"dungml": ROOM}, headers=SVC)
    r = client.post("/maps/i2/reveal", json={"feature_id": "room.does-not-exist"}, headers=SVC)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_reveal_marks_known_node(client):
    client.post("/maps/i3/fragments", json={"dungml": ROOM}, headers=SVC)
    r = client.post("/maps/i3/reveal", json={"feature_id": "room.hall"}, headers=SVC)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_tokens_mint(client):
    client.post("/maps/i4/fragments", json={"dungml": ROOM}, headers=SVC)
    r = client.post("/maps/i4/tokens", json={"scope": "fog"}, headers=SVC)
    assert r.status_code == 200 and r.json()["token"]
