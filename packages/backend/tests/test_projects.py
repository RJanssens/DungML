"""Projects CRUD + ownership."""
from __future__ import annotations


def test_list_requires_auth(client):
    assert client.get("/api/projects").status_code == 401


def test_empty_list_for_new_user(auth_client):
    r = auth_client.get("/api/projects")
    assert r.status_code == 200
    assert r.json() == []


def test_create_then_list(auth_client):
    r = auth_client.post("/api/projects", json={"name": "First"})
    assert r.status_code == 201
    pid = r.json()["id"]

    r = auth_client.get("/api/projects")
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == pid
    assert items[0]["name"] == "First"


def test_rename(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "Old"}).json()["id"]
    r = auth_client.patch(f"/api/projects/{pid}", json={"name": "New"})
    assert r.status_code == 200
    assert r.json()["name"] == "New"


def test_delete(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "X"}).json()["id"]
    r = auth_client.delete(f"/api/projects/{pid}")
    assert r.status_code == 204
    r = auth_client.get(f"/api/projects/{pid}")
    assert r.status_code == 404


def test_validation_rejects_empty_name(auth_client):
    r = auth_client.post("/api/projects", json={"name": ""})
    assert r.status_code == 422


def test_other_user_cannot_see_or_touch(client):
    """User A creates a project; user B sees 404, not 403, on all routes."""
    a = client.post(
        "/api/auth/register", json={"email": "a@x.com", "password": "longenough"}
    ).json()
    pid = client.post(
        "/api/projects",
        json={"name": "secret"},
        headers={"Authorization": f"Bearer {a['token']}"},
    ).json()["id"]

    b = client.post(
        "/api/auth/register", json={"email": "b@x.com", "password": "longenough"}
    ).json()
    h = {"Authorization": f"Bearer {b['token']}"}
    assert client.get(f"/api/projects/{pid}", headers=h).status_code == 404
    assert client.patch(
        f"/api/projects/{pid}", json={"name": "stolen"}, headers=h,
    ).status_code == 404
    assert client.delete(f"/api/projects/{pid}", headers=h).status_code == 404
    # B's own list is still empty.
    assert client.get("/api/projects", headers=h).json() == []


def test_get_nonexistent_returns_404(auth_client):
    r = auth_client.get("/api/projects/nonexistent-id")
    assert r.status_code == 404


def test_import_samples_creates_project_with_maps(auth_client):
    r = auth_client.post("/api/projects/import-samples")
    assert r.status_code == 201
    proj = r.json()
    assert proj["name"].startswith("Example")

    # The new project should contain at least the three bundled samples.
    maps = auth_client.get(f"/api/projects/{proj['id']}/maps").json()
    assert len(maps) >= 3
    names = {m["name"] for m in maps}
    assert "The Sunken Library of Cael Voren" in names
    assert "Miller's Cottage" in names
    assert "Crypt of Saint Vellis" in names

    # Each sample is real DSL — render one to confirm the source is intact.
    cottage = next(m for m in maps if m["name"] == "Miller's Cottage")
    detail = auth_client.get(f"/api/maps/{cottage['id']}").json()
    assert "# Miller's Cottage" in detail["source"]


def test_import_samples_requires_auth(client):
    assert client.post("/api/projects/import-samples").status_code == 401


# ----- core.dmap seeding -----

def test_new_project_seeds_core_dmap(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    maps = auth_client.get(f"/api/projects/{pid}/maps").json()
    core = [m for m in maps if m["name"] == "core.dmap"]
    assert len(core) == 1
    # It's a library (no `map "..."` block) and carries the bundled content.
    assert core[0]["kind"] == "library"
    detail = auth_client.get(f"/api/maps/{core[0]['id']}").json()
    assert 'feature_def "pillar"' in detail["source"]


def test_import_samples_seeds_core_dmap(auth_client):
    pid = auth_client.post("/api/projects/import-samples").json()["id"]
    names = {
        m["name"] for m in auth_client.get(f"/api/projects/{pid}/maps").json()
    }
    assert "core.dmap" in names


def test_backfill_adds_core_to_legacy_project(auth_client):
    """A project missing its core.dmap (e.g. created before seeding existed)
    gains one when backfill runs."""
    from dungml_backend.db import get_sessionmaker
    from dungml_backend.library import backfill_core_maps

    pid = auth_client.post("/api/projects", json={"name": "Legacy"}).json()["id"]
    # Simulate a pre-seeding project by removing the seeded core.dmap.
    maps = auth_client.get(f"/api/projects/{pid}/maps").json()
    core_id = next(m["id"] for m in maps if m["name"] == "core.dmap")
    assert auth_client.delete(f"/api/maps/{core_id}").status_code == 204

    session = get_sessionmaker()()
    try:
        added = backfill_core_maps(session)
    finally:
        session.close()
    assert added >= 1

    names = {
        m["name"] for m in auth_client.get(f"/api/projects/{pid}/maps").json()
    }
    assert "core.dmap" in names


def test_backfill_is_idempotent(auth_client):
    from dungml_backend.db import get_sessionmaker
    from dungml_backend.library import backfill_core_maps

    auth_client.post("/api/projects", json={"name": "P"})
    session = get_sessionmaker()()
    try:
        # Every project already has core.dmap, so nothing to add.
        assert backfill_core_maps(session) == 0
    finally:
        session.close()


# ----- bundled library catalog + import -----

def test_library_catalog_lists_bundled_with_added_flag(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    catalog = auth_client.get(f"/api/projects/{pid}/library-catalog").json()
    by_name = {e["name"]: e["added"] for e in catalog}
    # core.dmap is seeded, so it's already added; outdoor/forest are not.
    assert by_name.get("core.dmap") is True
    assert by_name.get("outdoor.dmap") is False
    assert "forest.dmap" in by_name


def test_import_library_creates_editable_copy(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    r = auth_client.post(
        f"/api/projects/{pid}/import-library", json={"name": "outdoor.dmap"}
    )
    assert r.status_code == 201
    m = r.json()
    assert m["name"] == "outdoor.dmap"
    assert m["kind"] == "library"
    assert 'feature_def "tree"' in m["source"]
    # Now flagged as added in the catalog.
    catalog = auth_client.get(f"/api/projects/{pid}/library-catalog").json()
    assert {e["name"]: e["added"] for e in catalog}["outdoor.dmap"] is True


def test_imported_library_overrides_bundled_in_render(auth_client):
    """After import, edits to the project copy drive the map's render."""
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    lib_id = auth_client.post(
        f"/api/projects/{pid}/import-library", json={"name": "outdoor.dmap"}
    ).json()["id"]
    # Reskin `tree` in the project copy with a sentinel class.
    auth_client.put(
        f"/api/maps/{lib_id}",
        json={
            "source": 'feature_def "tree" {\n'
            '  glyph { circle plain at 0,0 radius 0.4 class "sentinel" }\n'
            "}\n"
        },
    )
    map_id = auth_client.post(
        f"/api/projects/{pid}/maps",
        json={
            "name": "M",
            "source": (
                'include "outdoor.dmap"\n'
                'map "M" { grid { bounds 10 x 10 } }\n'
                "feature tree at 5,5\n"
            ),
        },
    ).json()["id"]
    svg = auth_client.get(f"/api/maps/{map_id}/render").text
    assert "sentinel" in svg


def test_import_library_unknown_404(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    r = auth_client.post(
        f"/api/projects/{pid}/import-library", json={"name": "nope.dmap"}
    )
    assert r.status_code == 404


def test_import_library_conflict_409(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    auth_client.post(
        f"/api/projects/{pid}/import-library", json={"name": "forest.dmap"}
    )
    again = auth_client.post(
        f"/api/projects/{pid}/import-library", json={"name": "forest.dmap"}
    )
    assert again.status_code == 409
    # core.dmap is seeded at creation, so importing it also conflicts.
    assert auth_client.post(
        f"/api/projects/{pid}/import-library", json={"name": "core.dmap"}
    ).status_code == 409


def test_library_catalog_requires_ownership(client):
    a = client.post(
        "/api/auth/register", json={"email": "a@x.com", "password": "longenough"}
    ).json()
    pid = client.post(
        "/api/projects", json={"name": "P"},
        headers={"Authorization": f"Bearer {a['token']}"},
    ).json()["id"]
    b = client.post(
        "/api/auth/register", json={"email": "b@x.com", "password": "longenough"}
    ).json()
    hb = {"Authorization": f"Bearer {b['token']}"}
    assert client.get(
        f"/api/projects/{pid}/library-catalog", headers=hb
    ).status_code == 404
    assert client.post(
        f"/api/projects/{pid}/import-library",
        json={"name": "forest.dmap"}, headers=hb,
    ).status_code == 404
