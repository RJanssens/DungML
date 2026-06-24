"""Auth route smoke tests for the OIDC migration.

After Task 4, /register and /login are gone (404); /me returns the principal.
The auth_client fixture is still password-based (fixed in Task 5), so the
/me test uses an inline static bearer token so this task is self-contained.
"""
from __future__ import annotations


def test_register_and_login_are_gone(client):
    assert client.post("/api/auth/register", json={"email": "a@b.c", "password": "x"}).status_code == 404
    assert client.post("/api/auth/login", json={"email": "a@b.c", "password": "x"}).status_code == 404


def test_me_returns_principal(client):
    # Use the default static dev token (DUNGML_DEV_TOKEN defaults to "dev-user").
    client.headers["Authorization"] = "Bearer dev-user"
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["subject"]  # the dev-user subject
