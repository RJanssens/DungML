# packages/backend/tests/test_contract_e2e.py
# End-to-end contract test: fragments → reveal → tokens → render.
#
# NOTE: The brief's single-line MAP source used invalid grid/room syntax
# (`grid { width 20 height 20 }` inline). The corrected form uses the
# multi-statement block syntax established in Tasks 3–4:
#   `grid { bounds 20 x 20 }` and `rect 0,0 8 x 8` in a room block.
SVC = {"Authorization": "Bearer dev-service"}
MAP = 'map "M" {\n  grid { bounds 20 x 20 }\n}\n\nroom "hall" {\n  rect 0,0 8 x 8\n}\n'


def test_full_contract_flow(client):
    assert client.post("/maps/e1/fragments", json={"dungml": MAP}, headers=SVC).status_code == 200
    assert client.post("/maps/e1/reveal", json={"feature_id": "room.hall"}, headers=SVC).status_code == 200
    tok = client.post("/maps/e1/tokens", json={"scope": "fog"}, headers=SVC).json()["token"]
    r = client.get(f"/maps/e1/render?token={tok}")
    assert r.status_code == 200 and "<svg" in r.text
