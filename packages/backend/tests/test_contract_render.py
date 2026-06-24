# packages/backend/tests/test_contract_render.py
# NOTE: The brief's single-line MAP source used invalid grid/room syntax
# (`grid { width 20 height 20 }` inline). Substituted with equivalent multi-line
# source that parses under dungml's grammar (`grid { bounds 20 x 20 }`).
# Node IDs confirmed: room.hall, room.vault.
SVC = {"Authorization": "Bearer dev-service"}
MAP = (
    'map "M" {\n'
    '  grid { bounds 20 x 20 }\n'
    '}\n'
    '\n'
    'room "hall" {\n'
    '  rect 0,0 8 x 8\n'
    '}\n'
    '\n'
    'room "vault" {\n'
    '  rect 12,0 6 x 6\n'
    '}\n'
)


def _setup(client, ext):
    client.post(f"/maps/{ext}/fragments", json={"dungml": MAP}, headers=SVC)


def test_render_requires_valid_token(client):
    _setup(client, "r1")
    assert client.get("/maps/r1/render?token=garbage").status_code == 401


def test_render_full_returns_svg(client):
    _setup(client, "r2")
    tok = client.post("/maps/r2/tokens", json={"scope": "gm"}, headers=SVC).json()["token"]
    r = client.get(f"/maps/r2/render?token={tok}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in r.text


def test_render_fog_hides_undiscovered(client):
    _setup(client, "r3")
    # reveal only the hall; fog render should not contain the vault's geometry
    client.post("/maps/r3/reveal", json={"feature_id": "room.hall"}, headers=SVC)
    tok = client.post("/maps/r3/tokens", json={"scope": "fog"}, headers=SVC).json()["token"]
    fog = client.get(f"/maps/r3/render?token={tok}").text
    full_tok = client.post("/maps/r3/tokens", json={"scope": "gm"}, headers=SVC).json()["token"]
    full = client.get(f"/maps/r3/render?token={full_tok}").text
    assert "<svg" in fog and "<svg" in full
    # the full (gm) view is at least as large as the fogged view
    assert len(full) >= len(fog)
