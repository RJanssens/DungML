"""Auth smoke tests after OIDC migration.

The old register/login/logout/password routes are gone (404); those flows
are covered by test_auth_routes.py.  These tests exercise the surviving
surface: unauthenticated 401, /me with a bearer token, and token-format
rejection.
"""
from __future__ import annotations


def test_health_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_current_user(auth_client):
    r = auth_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["subject"] == "dev-user"


def test_invalid_token_format_rejected(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Token abc"})
    assert r.status_code == 401
