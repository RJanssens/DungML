"""Default renderable-map designation per project."""
from __future__ import annotations

from dungml_backend import db, models


def test_ensure_columns_adds_is_default_idempotently(client):
    # `client` fixture has already run init_schema() + create_app() (which
    # runs ensure_columns in lifespan). Calling again must not error.
    db.ensure_columns()
    db.ensure_columns()
    from sqlalchemy import inspect
    cols = {c["name"] for c in inspect(db.get_engine()).get_columns("maps")}
    assert "is_default" in cols


def test_map_defaults_to_not_default(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    mid = auth_client.post(
        f"/api/projects/{pid}/maps",
        json={"name": "M", "source": 'map "M" { grid { bounds 5 x 5 } }'},
    ).json()["id"]
    m = db.get_sessionmaker()().get(models.Map, mid)
    assert m.is_default is False  # no auto-assign yet — added in Task 3
