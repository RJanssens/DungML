"""Timestamps leave the API as UTC, with the offset stated.

They are stored as naive UTC (SQLite keeps no timezone), and used to be sent
that way too: `"2026-09-26T12:43:41"`. ISO 8601 reads a bare timestamp as
*local* time, so the web app's "Updated 2 h ago" was off by the browser's UTC
offset. Every timestamp the API returns must now say it is UTC.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

OWNER = {"Authorization": "Bearer dev-user"}


def _aware_utc_and_recent(value: str) -> None:
    ts = datetime.fromisoformat(value)
    assert ts.utcoffset() == timedelta(0), f"{value!r} carries no UTC offset"
    # recent in *UTC*: a naive value read as local time is off by hours
    assert abs(datetime.now(timezone.utc) - ts) < timedelta(minutes=1)


def test_project_timestamps_are_utc(client):
    created = client.post("/api/projects", json={"name": "P"}, headers=OWNER).json()
    _aware_utc_and_recent(created["created_at"])
    _aware_utc_and_recent(created["updated_at"])
    listed = client.get("/api/projects", headers=OWNER).json()[0]
    _aware_utc_and_recent(listed["updated_at"])
    renamed = client.patch(f"/api/projects/{created['id']}", json={"name": "Q"}, headers=OWNER).json()
    _aware_utc_and_recent(renamed["updated_at"])


def test_map_timestamps_are_utc(client, cottage_source):
    pid = client.post("/api/projects", json={"name": "P"}, headers=OWNER).json()["id"]
    m = client.post(f"/api/projects/{pid}/maps", json={"name": "M", "source": cottage_source},
                    headers=OWNER).json()
    _aware_utc_and_recent(m["updated_at"])
    for row in client.get(f"/api/projects/{pid}/maps", headers=OWNER).json():
        _aware_utc_and_recent(row["updated_at"])
    put = client.put(f"/api/maps/{m['id']}", json={"source": cottage_source + "\n"}, headers=OWNER).json()
    _aware_utc_and_recent(put["updated_at"])
    assert datetime.fromisoformat(put["updated_at"]) >= datetime.fromisoformat(m["updated_at"])


def test_session_timestamps_are_utc(client, cottage_source):
    pid = client.post("/api/projects", json={"name": "P"}, headers=OWNER).json()["id"]
    mid = client.post(f"/api/projects/{pid}/maps", json={"name": "M", "source": cottage_source},
                      headers=OWNER).json()["id"]
    assert client.post(f"/api/maps/{mid}/sessions", json={"name": "s"}, headers=OWNER).status_code == 201
    rows = client.get(f"/api/projects/{pid}/sessions", headers=OWNER).json()
    assert rows and all(_aware_utc_and_recent(r["updated_at"]) is None for r in rows)


def test_storage_is_still_naive_utc(client, db_path):
    """The fix is at the edges: rows already on disk and rows written now look
    the same, so no migration and no mixed formats in one column."""
    client.post("/api/projects", json={"name": "P"}, headers=OWNER)
    with sqlite3.connect(db_path) as con:
        raw = con.execute("SELECT created_at, updated_at FROM projects").fetchone()
    for v in raw:
        assert "+" not in v and not v.endswith("Z"), v
        assert abs(datetime.now(timezone.utc).replace(tzinfo=None) - datetime.fromisoformat(v)) < timedelta(minutes=1)


def test_a_naive_row_from_before_the_fix_reads_as_utc(client, db_path):
    pid = client.post("/api/projects", json={"name": "P"}, headers=OWNER).json()["id"]
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE projects SET updated_at = '2026-01-02 03:04:05.000006' WHERE id = ?", (pid,))
    got = client.get(f"/api/projects/{pid}", headers=OWNER).json()["updated_at"]
    assert datetime.fromisoformat(got) == datetime(2026, 1, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
