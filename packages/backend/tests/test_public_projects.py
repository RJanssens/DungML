"""Public projects: every signed-in user gets member rights on a public one.

`dev-service` stands in for "another user", as in test_project_members.py —
static auth ships two principals.
"""
from __future__ import annotations

import sqlite3

from dungml_backend import contract, db, models

OWNER = {"Authorization": "Bearer dev-user"}
OTHER = {"Authorization": "Bearer dev-service"}


def _row(pid: str) -> models.Project:
    return db.get_sessionmaker()().get(models.Project, pid)


# ---- Task 1: storage and defaults ----


def test_new_project_is_public_by_default(client):
    pid = client.post("/api/projects", json={"name": "P"}, headers=OWNER).json()["id"]
    assert _row(pid).is_public is True


def test_project_can_be_created_private(client):
    pid = client.post(
        "/api/projects", json={"name": "P", "is_public": False}, headers=OWNER
    ).json()["id"]
    assert _row(pid).is_public is False


def test_example_project_is_private(client):
    pid = client.post("/api/projects/import-samples", headers=OWNER).json()["id"]
    assert _row(pid).is_public is False


def test_service_project_is_private(client):
    s = db.get_sessionmaker()()
    m = contract.get_or_create_map(s, "combat-1")
    assert s.get(models.Project, m.project_id).is_public is False


def test_migration_makes_existing_public_except_service_and_examples(client, db_path):
    ordinary = client.post("/api/projects", json={"name": "Ordinary"}, headers=OWNER).json()["id"]
    example = client.post("/api/projects/import-samples", headers=OWNER).json()["id"]
    s = db.get_sessionmaker()()
    service = contract.get_or_create_map(s, "combat-1").project_id
    s.close()
    # an ordinary project the owner once named like the service project stays public:
    lookalike = client.post(
        "/api/projects", json={"name": contract._SERVICE_PROJECT}, headers=OWNER
    ).json()["id"]
    with sqlite3.connect(db_path) as con:
        con.execute("ALTER TABLE projects DROP COLUMN is_public")   # a pre-feature DB

    db.ensure_columns()

    with sqlite3.connect(db_path) as con:
        got = dict(con.execute("SELECT id, is_public FROM projects").fetchall())
    assert got == {ordinary: 1, example: 0, service: 0, lookalike: 1}


def test_migration_runs_once_so_an_owner_choice_sticks(client, db_path):
    example = client.post("/api/projects/import-samples", headers=OWNER).json()["id"]
    with sqlite3.connect(db_path) as con:
        con.execute("ALTER TABLE projects DROP COLUMN is_public")
    db.ensure_columns()
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE projects SET is_public = 1 WHERE id = ?", (example,))
    db.ensure_columns()   # every boot calls it
    assert _row(example).is_public is True
