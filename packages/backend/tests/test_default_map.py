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


def test_first_map_is_default(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    mid = auth_client.post(
        f"/api/projects/{pid}/maps",
        json={"name": "M", "source": 'map "M" { grid { bounds 5 x 5 } }'},
    ).json()["id"]
    m = db.get_sessionmaker()().get(models.Map, mid)
    assert m.is_default is True


from dungml_backend import defaults

_RENDERABLE = 'map "X" { grid { bounds 5 x 5 } }'
_LIBRARY = 'feature_def "w" { name "W" shape rect 1 x 1 }'


def _mk(session, project_id, name, source):
    m = models.Map(project_id=project_id, name=name, source=source)
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def test_ensure_project_default_marks_first_renderable(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    s = db.get_sessionmaker()()
    # Fresh project has only the seeded core.dmap library → no renderable yet.
    m1 = _mk(s, pid, "a", _RENDERABLE)
    m2 = _mk(s, pid, "b", _RENDERABLE)
    got = defaults.ensure_project_default(s, pid)
    assert got.id == m1.id
    s.refresh(m1); s.refresh(m2)
    assert m1.is_default is True and m2.is_default is False
    # Idempotent: a second call keeps the same default.
    assert defaults.ensure_project_default(s, pid).id == m1.id


def test_ensure_project_default_ignores_libraries(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    s = db.get_sessionmaker()()
    _mk(s, pid, "lib", _LIBRARY)
    # core.dmap + this lib are both libraries → nothing to default.
    assert defaults.ensure_project_default(s, pid) is None


def test_set_default_map_moves_the_flag(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    s = db.get_sessionmaker()()
    m1 = _mk(s, pid, "a", _RENDERABLE)
    m2 = _mk(s, pid, "b", _RENDERABLE)
    defaults.set_default_map(s, pid, m1.id)
    defaults.set_default_map(s, pid, m2.id)
    s.refresh(m1); s.refresh(m2)
    assert m1.is_default is False and m2.is_default is True


def test_set_default_map_rejects_library_and_foreign(auth_client):
    import pytest
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    s = db.get_sessionmaker()()
    lib = _mk(s, pid, "lib2", _LIBRARY)
    with pytest.raises(ValueError):
        defaults.set_default_map(s, pid, lib.id)
    with pytest.raises(ValueError):
        defaults.set_default_map(s, pid, "no-such-map")


def test_first_created_map_is_auto_default(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    m1 = auth_client.post(
        f"/api/projects/{pid}/maps", json={"name": "A", "source": _RENDERABLE}
    ).json()
    m2 = auth_client.post(
        f"/api/projects/{pid}/maps", json={"name": "B", "source": _RENDERABLE}
    ).json()
    s = db.get_sessionmaker()()
    assert s.get(models.Map, m1["id"]).is_default is True
    assert s.get(models.Map, m2["id"]).is_default is False


def test_import_samples_has_exactly_one_default(auth_client):
    pid = auth_client.post("/api/projects/import-samples").json()["id"]
    s = db.get_sessionmaker()()
    from sqlalchemy import select
    maps = s.scalars(select(models.Map).where(models.Map.project_id == pid)).all()
    defaults_ = [m for m in maps if m.is_default]
    assert len(defaults_) == 1
    assert defaults_[0].kind == "map"


def test_put_default_route_sets_and_reports(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    a = auth_client.post(
        f"/api/projects/{pid}/maps", json={"name": "A", "source": _RENDERABLE}
    ).json()  # auto-default
    b = auth_client.post(
        f"/api/projects/{pid}/maps", json={"name": "B", "source": _RENDERABLE}
    ).json()
    r = auth_client.put(f"/api/projects/{pid}/maps/{b['id']}/default")
    assert r.status_code == 200
    assert r.json()["is_default"] is True
    # Summary list now reports b as the default, a as not.
    items = {m["id"]: m for m in auth_client.get(f"/api/projects/{pid}/maps").json()}
    assert items[b["id"]]["is_default"] is True
    assert items[a["id"]]["is_default"] is False


def test_put_default_rejects_library_and_missing(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    auth_client.post(
        f"/api/projects/{pid}/maps", json={"name": "A", "source": _RENDERABLE}
    )
    lib = auth_client.post(
        f"/api/projects/{pid}/maps", json={"name": "lib", "source": _LIBRARY}
    ).json()
    assert auth_client.put(f"/api/projects/{pid}/maps/{lib['id']}/default").status_code == 400
    assert auth_client.put(f"/api/projects/{pid}/maps/nope/default").status_code == 404
