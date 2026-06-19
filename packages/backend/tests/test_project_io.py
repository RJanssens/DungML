"""Project export → import round-trip (the .dmapproj archive)."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

MAP_A = 'map "A" { grid { bounds 20 x 20 } }\nroom "r" { rect 1,1 4 x 4 }\n'
MAP_B = 'map "B" { grid { bounds 10 x 10 } }\n'


@pytest.fixture
def project_id(auth_client) -> str:
    pid = auth_client.post("/api/projects", json={"name": "Dungeon"}).json()["id"]
    auth_client.post(f"/api/projects/{pid}/maps", json={"name": "Level 1", "source": MAP_A})
    auth_client.post(f"/api/projects/{pid}/maps", json={"name": "Level 2", "source": MAP_B})
    return pid


def test_export_returns_zip_with_manifest_and_maps(auth_client, project_id):
    r = auth_client.get(f"/api/projects/{project_id}/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert ".dmapproj" in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["format"] == "dungml-project"
    assert manifest["name"] == "Dungeon"
    names = {m["name"] for m in manifest["maps"]}
    assert {"Level 1", "Level 2"} <= names
    # The map sources are stored verbatim in their files.
    by_name = {m["name"]: m["file"] for m in manifest["maps"]}
    assert zf.read(by_name["Level 1"]).decode() == MAP_A


def test_import_recreates_project(auth_client, project_id):
    blob = auth_client.get(f"/api/projects/{project_id}/export").content
    r = auth_client.post(
        "/api/projects/import",
        files={"file": ("dungeon.dmapproj", blob, "application/zip")},
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    assert new_id != project_id
    assert r.json()["name"] == "Dungeon"
    maps = auth_client.get(f"/api/projects/{new_id}/maps").json()
    names = {m["name"] for m in maps}
    assert {"Level 1", "Level 2"} <= names


def test_import_rejects_non_archive(auth_client):
    r = auth_client.post(
        "/api/projects/import",
        files={"file": ("bad.dmapproj", b"not a zip", "application/zip")},
    )
    assert r.status_code == 400


def test_import_rejects_foreign_zip(auth_client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "world")
    r = auth_client.post(
        "/api/projects/import",
        files={"file": ("x.dmapproj", buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 400


def test_export_requires_ownership(client, auth_client, project_id):
    other = client.post(
        "/api/auth/register",
        json={"email": "other@x.com", "password": "longenough"},
    ).json()
    r = client.get(
        f"/api/projects/{project_id}/export",
        headers={"Authorization": f"Bearer {other['token']}"},
    )
    assert r.status_code == 404
