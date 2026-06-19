"""Auth: register, login, logout, me, password hashing edge cases."""
from __future__ import annotations


def test_health_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_register_returns_token_and_user(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "a@b.com", "password": "verystrong"},
    )
    assert r.status_code == 201
    body = r.json()
    assert "token" in body and len(body["token"]) >= 32
    assert body["user"]["email"] == "a@b.com"
    assert body["user"]["id"]


def test_register_duplicate_email_conflicts(client):
    payload = {"email": "x@y.com", "password": "verystrong"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 409


def test_register_rejects_short_password(client):
    r = client.post(
        "/api/auth/register", json={"email": "a@b.com", "password": "short"}
    )
    assert r.status_code == 422


def test_login_returns_new_token(client):
    client.post(
        "/api/auth/register",
        json={"email": "a@b.com", "password": "verystrong"},
    )
    r = client.post(
        "/api/auth/login", json={"email": "a@b.com", "password": "verystrong"}
    )
    assert r.status_code == 200
    assert r.json()["token"]


def test_login_bad_password_401(client):
    client.post(
        "/api/auth/register",
        json={"email": "a@b.com", "password": "verystrong"},
    )
    r = client.post(
        "/api/auth/login", json={"email": "a@b.com", "password": "wrong-one"}
    )
    assert r.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_current_user(auth_client):
    r = auth_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "user@example.com"


def test_logout_revokes_token(auth_client):
    r = auth_client.post("/api/auth/logout")
    assert r.status_code == 204
    # Subsequent calls fail.
    assert auth_client.get("/api/auth/me").status_code == 401


def test_logout_is_idempotent(client):
    r = client.post("/api/auth/logout")  # no auth header
    assert r.status_code == 204
    r = client.post("/api/auth/logout", headers={"Authorization": "Bearer junk"})
    assert r.status_code == 204


def test_invalid_token_format_rejected(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Token abc"})
    assert r.status_code == 401


def test_password_hashing_roundtrip():
    from dungml_backend.auth import hash_password, verify_password

    stored = hash_password("hunter2!")
    assert stored.startswith("scrypt$")
    assert verify_password("hunter2!", stored)
    assert not verify_password("hunter2", stored)
    assert not verify_password("", stored)
