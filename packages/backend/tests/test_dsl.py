"""DSL routes: stateless ops + stored-map convenience routes."""
from __future__ import annotations

import pytest


# ----- stateless parse / validate / render -----

def test_renderers_lists_classic_bw(client):
    r = client.get("/api/dsl/renderers")
    assert r.status_code == 200
    assert "classic-bw" in r.json()


def test_parse_round_trip(client, cottage_source):
    r = client.post("/api/dsl/parse", json={"source": cottage_source})
    assert r.status_code == 200
    parsed = r.json()["map"]
    assert parsed["map"]["name"] == "Miller's Cottage"
    assert set(parsed["rooms"].keys()) == {"kitchen", "parlor", "bedroom"}


def test_parse_error_returns_400(client):
    r = client.post("/api/dsl/parse", json={"source": 'map "X" {'})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "message" in detail


def test_validate_clean_sample(client, crypt_source):
    r = client.post("/api/dsl/validate", json={"source": crypt_source})
    assert r.status_code == 200
    assert r.json()["diagnostics"] == []


def test_validate_parse_failure_returned_as_diagnostic(client):
    """Parse failures shouldn't 400 on /validate — the editor needs a
    diagnostic, not an HTTP error, to render a squiggle."""
    r = client.post("/api/dsl/validate", json={"source": 'map "X" {'})
    assert r.status_code == 200
    diags = r.json()["diagnostics"]
    assert len(diags) == 1
    assert diags[0]["severity"] == "error"


def test_validate_reports_undefined_feature(client):
    src = (
        'map "T" { grid { bounds 10 x 10 } }\n'
        'room "r" { rect 0,0 5 x 5\n  feature unknown_thing at 2,2\n}'
    )
    r = client.post("/api/dsl/validate", json={"source": src})
    diags = r.json()["diagnostics"]
    assert any("unknown_thing" in d["message"] for d in diags)


def test_render_returns_svg_and_diagnostics(client, cottage_source):
    r = client.post("/api/dsl/render", json={"source": cottage_source})
    assert r.status_code == 200
    body = r.json()
    assert body["svg"].startswith("<svg")
    assert body["diagnostics"] == []


def test_render_with_explicit_renderer(client, cottage_source):
    r = client.post(
        "/api/dsl/render",
        json={"source": cottage_source, "renderer": "classic-bw"},
    )
    assert r.status_code == 200
    assert r.json()["svg"].startswith("<svg")


def test_render_unknown_renderer_400(client, cottage_source):
    r = client.post(
        "/api/dsl/render",
        json={"source": cottage_source, "renderer": "no-such"},
    )
    assert r.status_code == 400


def test_render_parse_failure_400(client):
    r = client.post("/api/dsl/render", json={"source": "totally not a map"})
    assert r.status_code == 400


# ----- stored-map convenience routes -----

@pytest.fixture
def stored_map(auth_client, cottage_source) -> tuple[str, str]:
    pid = auth_client.post("/api/projects", json={"name": "P"}).json()["id"]
    mid = auth_client.post(
        f"/api/projects/{pid}/maps",
        json={"name": "Cottage", "source": cottage_source},
    ).json()["id"]
    return pid, mid


def test_render_stored_map_returns_svg_media_type(auth_client, stored_map):
    _, mid = stored_map
    r = auth_client.get(f"/api/maps/{mid}/render")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert r.text.startswith("<svg")


def test_render_stored_map_renderer_override(auth_client, stored_map):
    _, mid = stored_map
    r = auth_client.get(f"/api/maps/{mid}/render?renderer=classic-bw")
    assert r.status_code == 200


def test_validate_stored_map(auth_client, stored_map):
    _, mid = stored_map
    r = auth_client.get(f"/api/maps/{mid}/validate")
    assert r.status_code == 200
    assert r.json()["diagnostics"] == []


def test_render_stored_map_requires_auth(client, stored_map):
    _, mid = stored_map
    # The stored_map fixture sets Authorization via auth_client; drop it.
    client.headers.pop("Authorization", None)
    assert client.get(f"/api/maps/{mid}/render").status_code == 401


def test_render_uses_project_core_override(auth_client, stored_map):
    """Editing the project's core.dmap changes how a sibling map renders —
    the renderer reads the project copy, not the bundled library."""
    pid, mid = stored_map
    maps = auth_client.get(f"/api/projects/{pid}/maps").json()
    core_id = next(m["id"] for m in maps if m["name"] == "core.dmap")
    # Override the project's `chair` glyph (cottage places several) with a
    # sentinel marker class.
    auth_client.put(
        f"/api/maps/{core_id}",
        json={
            "source": 'feature_def "chair" {\n'
            '  glyph { circle fill at 0,0 radius 0.42 class "sentinel" }\n'
            "}\n"
        },
    )
    r = auth_client.get(f"/api/maps/{mid}/render")
    assert r.status_code == 200
    assert "sentinel" in r.text


def test_post_render_uses_live_source_and_project_includes(
    auth_client, stored_map
):
    """The editor preview POSTs an unsaved buffer; includes still resolve
    against the project's core.dmap."""
    _, mid = stored_map
    src = (
        'include "core.dmap"\n'
        'map "Live" { grid { bounds 12 x 12 } }\n'
        'room "r" { rect 0,0 6 x 6 }\n'
        "feature pillar at 3,3\n"
    )
    r = auth_client.post(f"/api/maps/{mid}/render", json={"source": src})
    assert r.status_code == 200
    body = r.json()
    assert body["svg"].startswith("<svg")
    # pillar resolves via the project core, so no "unknown feature" error.
    assert body["diagnostics"] == []


def test_post_validate_reports_clean_with_project_core(auth_client, stored_map):
    _, mid = stored_map
    src = (
        'include "core.dmap"\n'
        'map "V" { grid { bounds 10 x 10 } }\n'
        'room "r" { rect 0,0 5 x 5 }\n'
        "feature pillar at 2,2\n"
    )
    r = auth_client.post(f"/api/maps/{mid}/validate", json={"source": src})
    assert r.status_code == 200
    assert r.json()["diagnostics"] == []


def test_post_render_falls_back_to_stored_source(auth_client, stored_map):
    _, mid = stored_map
    r = auth_client.post(f"/api/maps/{mid}/render", json={})
    assert r.status_code == 200
    assert r.json()["svg"].startswith("<svg")


def test_post_render_requires_auth(client, stored_map):
    _, mid = stored_map
    client.headers.pop("Authorization", None)
    assert client.post(f"/api/maps/{mid}/render", json={}).status_code == 401


def test_feature_names_from_includes(auth_client, stored_map):
    """The dropdown source: feature_defs the map's includes resolve to,
    sorted alphabetically (case-insensitive)."""
    _, mid = stored_map  # cottage source includes core.dmap
    r = auth_client.post(f"/api/maps/{mid}/feature-names", json={})
    assert r.status_code == 200
    names = r.json()["names"]
    assert "pillar" in names and "chest" in names
    assert names == sorted(names, key=str.lower)


def test_feature_names_grouped_by_include_file(auth_client, stored_map):
    """Groups split features by source file, sorted; flat `names` is the
    union. A locally-defined feature lands in the "(this file)" group."""
    _, mid = stored_map
    src = (
        'include "core.dmap"\n'
        'include "outdoor.dmap"\n'
        'map "M" { grid { bounds 10 x 10 } }\n'
        'feature_def "homebrew" { shape circle radius 0.3 }\n'
    )
    body = auth_client.post(
        f"/api/maps/{mid}/feature-names", json={"source": src}
    ).json()
    groups = {g["source"]: g["names"] for g in body["groups"]}
    assert "tree" in groups["outdoor.dmap"]
    assert "pillar" in groups["core.dmap"]
    assert groups["(this file)"] == ["homebrew"]
    # Group order alphabetical; names within each group sorted.
    sources = [g["source"] for g in body["groups"]]
    assert sources == sorted(sources, key=str.lower)
    for g in body["groups"]:
        assert g["names"] == sorted(g["names"], key=str.lower)
    # Flat names is the union of all groups.
    assert set(body["names"]) == {n for g in body["groups"] for n in g["names"]}


def test_feature_names_track_live_include(auth_client, stored_map):
    """Adding `include "outdoor.dmap"` surfaces its symbols; a source with
    no include returns no features (the list is dynamic, not static)."""
    _, mid = stored_map
    with_outdoor = (
        'include "outdoor.dmap"\n'
        'map "M" { grid { bounds 10 x 10 } }\n'
    )
    names = auth_client.post(
        f"/api/maps/{mid}/feature-names", json={"source": with_outdoor}
    ).json()["names"]
    assert {"tree", "mountain", "water"} <= set(names)
    assert "pillar" not in names  # core.dmap not included here

    no_include = 'map "M" { grid { bounds 10 x 10 } }\n'
    empty = auth_client.post(
        f"/api/maps/{mid}/feature-names", json={"source": no_include}
    ).json()["names"]
    assert empty == []


def test_feature_names_uses_project_core_override(auth_client, stored_map):
    """A feature_def added to the project's core.dmap shows up in the list."""
    pid, mid = stored_map
    maps = auth_client.get(f"/api/projects/{pid}/maps").json()
    core_id = next(m["id"] for m in maps if m["name"] == "core.dmap")
    auth_client.put(
        f"/api/maps/{core_id}",
        json={"source": 'feature_def "sigil" { shape circle radius 0.3 }\n'},
    )
    names = auth_client.post(
        f"/api/maps/{mid}/feature-names", json={}
    ).json()["names"]
    assert "sigil" in names


def test_render_stored_map_404_for_other_user(client, cottage_source):
    a = client.post(
        "/api/auth/register", json={"email": "a@x.com", "password": "longenough"}
    ).json()
    ha = {"Authorization": f"Bearer {a['token']}"}
    pid = client.post("/api/projects", json={"name": "P"}, headers=ha).json()["id"]
    mid = client.post(
        f"/api/projects/{pid}/maps",
        json={"name": "m", "source": cottage_source},
        headers=ha,
    ).json()["id"]
    b = client.post(
        "/api/auth/register", json={"email": "b@x.com", "password": "longenough"}
    ).json()
    hb = {"Authorization": f"Bearer {b['token']}"}
    assert client.get(f"/api/maps/{mid}/render", headers=hb).status_code == 404
