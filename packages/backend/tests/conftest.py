"""Shared fixtures: per-test SQLite DB, TestClient, authenticated client."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Configure a per-test sqlite path BEFORE importing app modules so the
# engine binds to the test database.
@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DUNGML_DB_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("DUNGML_TOKEN_TTL", "3600")
    # Reload config and reset the engine cache so the new URL takes effect.
    from dungml_backend import config, db
    config.reload_settings()
    db.reset_engine()
    db.init_schema()

    from dungml_backend.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client):
    """A TestClient with `Authorization: Bearer <token>` pre-set for a fresh user."""
    r = client.post(
        "/api/auth/register",
        json={"email": "user@example.com", "password": "correct horse"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


SAMPLES = Path(__file__).resolve().parents[3] / "samples"


@pytest.fixture
def cottage_source() -> str:
    return (SAMPLES / "cottage.dmap").read_text(encoding="utf-8")


@pytest.fixture
def crypt_source() -> str:
    return (SAMPLES / "crypt.dmap").read_text(encoding="utf-8")
