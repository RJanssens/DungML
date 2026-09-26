# Public Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project can be public, which gives every signed-in user member rights on it; new and existing projects are public except the ttrpg2 service project and per-user example projects.

**Architecture:** One boolean column, `projects.is_public`, checked in the single authorization module `access.py` (`can_access` = public or owner/member). Campaign linking keeps a stricter collaborator-only check. The API exposes `is_public` and the caller's `role`, the MCP server moves onto `access.py`, and the web app groups projects and gives the owner a toggle.

**Tech Stack:** FastAPI + SQLAlchemy 2 + SQLite (no Alembic: `db.ensure_columns()`), pytest; React + TanStack Query + vitest.

**Spec:** `docs/superpowers/specs/2026-09-26-public-projects-design.md`

## Global Constraints

- Work in the worktree `.claude/worktrees/public-projects`, branch `feat/public-projects` (based on `fix/utc-timestamps` → `feat/room-context`).
- No Alembic: a new column on an existing table goes into `db.ensure_columns()` **in the same commit** (CLAUDE.md).
- Every route authorizes through `access.py`; never compare `user_id` inline.
- Private project, no access → **404**; access but owner-only action → **403**.
- Owner-only: delete project, manage membership, change `is_public`.
- Campaign `link`/`unlink`: owner or member only (`is_collaborator`); everyone else 404.
- Private by default: the ttrpg2 service project (`contract._SERVICE_PROJECT`, owned by subject `contract._SERVICE_SUBJECT`) and the example project (`samples.EXAMPLE_PROJECT_NAME`).
- Static auth has two principals: `Bearer dev-user` (a person) and `Bearer dev-service` (the service). Tests use `dev-service` as "a second user", as the existing tests do.
- Run the whole suite before every commit: `uv run pytest packages/ -q` (577 passing at the start of this plan), and `cd packages/web && npm run test` for web tasks.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **A member of a project the owner makes private keeps access; a stranger loses it**, including a stranger who had it open. → Task 3, `test_owner_makes_private_member_keeps_stranger_loses`.
2. **The service principal on a public project it isn't linked to** can use `/api` like any user, but the service-scoped `/campaigns/{ext}/maps/{map_id}/…` routes must still 404 for a map outside the linked project. → Task 2, `test_campaign_routes_stay_bounded_to_the_linked_project`.
3. **A project that is public and also has the caller as owner or member** appears once in the list, with the stronger role. → Task 3, `test_list_has_no_duplicates_and_the_strongest_role`.
4. **A stranger unlinking someone else's campaign from a public project** gets 404 and the link survives. → Task 2, `test_stranger_cannot_unlink_from_a_public_project`.
5. **A non-owner on a public project must not see a Delete-project button.** It would 403, and seeing it is alarming. → Task 5, `test("a public project shows no Delete button")`.

---

### Task 1: `projects.is_public` — column, migration, creation defaults

**Files:**
- Modify: `packages/backend/src/dungml_backend/models.py` (class `Project`)
- Modify: `packages/backend/src/dungml_backend/db.py` (`ensure_columns`, append a block)
- Modify: `packages/backend/src/dungml_backend/schemas.py` (`ProjectIn`)
- Modify: `packages/backend/src/dungml_backend/routes/projects.py` (`create_project`, `import_samples`)
- Modify: `packages/backend/src/dungml_backend/contract.py` (`_service_project`)
- Test: `packages/backend/tests/test_public_projects.py` (new)

**Interfaces:**
- Produces: `models.Project.is_public: bool` (default `True`); `schemas.ProjectIn.is_public: bool = True`.

- [ ] **Step 1: Write the failing tests**

Create `packages/backend/tests/test_public_projects.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/backend/tests/test_public_projects.py -q`
Expected: FAIL, with `AttributeError: 'Project' object has no attribute 'is_public'` (and the migration tests failing on `DROP COLUMN is_public`, since there is no such column).

- [ ] **Step 3: Implement**

`models.py`, in `class Project`, after `name`:

```python
    # Public: every signed-in user gets member rights (see access.py). New
    # projects default to it; the service and example projects opt out.
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

`db.py`, append at the end of `ensure_columns()`:

```python
    # Public projects. Adding the column makes every existing project public
    # (the DEFAULT), then — in this branch only, so exactly once — the two
    # kinds that should not be are set private: the ttrpg2 service project
    # (ttrpg2 rewrites those maps on every token move) and each user's example
    # project (one identical copy per user). Doing it on every boot would undo
    # an owner who later made one of them public.
    if "projects" in existing and "is_public" not in cols("projects"):
        from .contract import _SERVICE_PROJECT, _SERVICE_SUBJECT
        from .samples import EXAMPLE_PROJECT_NAME

        sqlite = engine.dialect.name == "sqlite"
        yes, no = ("1", "0") if sqlite else ("true", "false")
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE projects ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT {yes}")
            )
            conn.execute(
                text(
                    f"UPDATE projects SET is_public = {no} WHERE name = :example "
                    "OR (name = :service AND user_id IN "
                    "(SELECT id FROM users WHERE subject = :subject))"
                ),
                {"example": EXAMPLE_PROJECT_NAME, "service": _SERVICE_PROJECT,
                 "subject": _SERVICE_SUBJECT},
            )
```

`schemas.py`, `ProjectIn`:

```python
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # New projects are public unless the creator says otherwise.
    is_public: bool = True
```

`routes/projects.py`, `create_project`:

```python
    proj = models.Project(user_id=user.id, name=body.name, is_public=body.is_public)
```

`routes/projects.py`, `import_samples`:

```python
    # Private: every user gets their own copy, so public ones would pile up.
    proj = models.Project(user_id=user.id, name=EXAMPLE_PROJECT_NAME, is_public=False)
```

`contract.py`, `_service_project`:

```python
    if p is None:
        # Private: ttrpg2 owns these maps and re-pushes their DSL on every token
        # move, so anyone else's edit would be silently overwritten.
        p = models.Project(user_id=u.id, name=_SERVICE_PROJECT, is_public=False)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_public_projects.py -q`
Expected: 6 passed.
Run: `uv run pytest packages/ -q`
Expected: all pass (583). Nothing reads `is_public` yet.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/dungml_backend/{models,db,schemas,contract}.py packages/backend/src/dungml_backend/routes/projects.py packages/backend/tests/test_public_projects.py
git commit -m "feat(projects): is_public column, public by default; service and example projects private

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Authorization — public projects in `access.py`, linking collaborator-only

**Files:**
- Modify: `packages/backend/src/dungml_backend/access.py`
- Modify: `packages/backend/src/dungml_backend/routes/campaigns.py` (`link`, `unlink`)
- Modify (private projects in tests that test privacy): `packages/backend/tests/test_maps.py:87`, `test_dsl.py:268`, `test_projects.py:51` and `:235`, `test_project_io.py:16`, `test_project_members.py:29`, `test_project_sessions.py:18`, `test_service_membership.py:16`, `test_sessions.py:18`, `test_campaign_visibility.py:154`
- Test: `packages/backend/tests/test_public_projects.py` (append)

**Interfaces:**
- Consumes: `models.Project.is_public` (Task 1).
- Produces: `access.is_collaborator(db, project, user) -> bool` (owner or member, ignoring public); `access.collaborator_project(db, project_id, user) -> Project | None`; `access.can_access` now returns true for public projects; `access.list_projects` now includes public projects.

- [ ] **Step 1: Write the failing tests** (append to `test_public_projects.py`)

```python
# ---- Task 2: access ----


def _public(client, name="Pub") -> str:
    return client.post("/api/projects", json={"name": name}, headers=OWNER).json()["id"]


def _private(client, name="Priv") -> str:
    return client.post(
        "/api/projects", json={"name": name, "is_public": False}, headers=OWNER
    ).json()["id"]


def test_stranger_sees_public_project_in_list(client):
    pid = _public(client)
    assert pid in [p["id"] for p in client.get("/api/projects", headers=OTHER).json()]


def test_stranger_does_not_see_private_project(client):
    pid = _private(client)
    assert pid not in [p["id"] for p in client.get("/api/projects", headers=OTHER).json()]
    assert client.get(f"/api/projects/{pid}", headers=OTHER).status_code == 404


def test_stranger_can_edit_maps_of_a_public_project(client, cottage_source):
    pid = _public(client)
    r = client.post(f"/api/projects/{pid}/maps", json={"name": "M", "source": cottage_source},
                    headers=OTHER)
    assert r.status_code == 201
    mid = r.json()["id"]
    assert client.put(f"/api/maps/{mid}", json={"source": cottage_source}, headers=OTHER).status_code == 200
    assert client.get(f"/api/maps/{mid}/render", headers=OTHER).status_code == 200


def test_stranger_gets_403_on_owner_only_actions_of_a_public_project(client):
    pid = _public(client)
    assert client.delete(f"/api/projects/{pid}", headers=OTHER).status_code == 403
    assert client.post(f"/api/projects/{pid}/members", json={"identifier": "dev-user"},
                       headers=OTHER).status_code == 403


def test_stranger_cannot_link_a_campaign_to_a_public_project(client):
    pid = _public(client)
    r = client.post("/campaigns/their-game/link", json={"project_id": pid}, headers=OTHER)
    assert r.status_code == 404


def test_stranger_cannot_unlink_from_a_public_project(client):
    pid = _public(client)
    assert client.post("/campaigns/g1/link", json={"project_id": pid}, headers=OWNER).status_code == 200
    assert client.delete("/campaigns/g1/link", headers=OTHER).status_code == 404
    s = db.get_sessionmaker()()
    assert s.get(models.CampaignLink, "g1") is not None


def test_campaign_routes_stay_bounded_to_the_linked_project(client, cottage_source):
    linked = _public(client, "Linked")
    other = _public(client, "Other")
    other_map = client.post(f"/api/projects/{other}/maps",
                            json={"name": "M", "source": cottage_source}, headers=OWNER).json()["id"]
    assert client.post("/campaigns/g1/link", json={"project_id": linked}, headers=OWNER).status_code == 200
    # public, so the service can read it through /api like anyone …
    assert client.get(f"/api/maps/{other_map}", headers=OTHER).status_code == 200
    # … but the campaign-scoped routes only reach the linked project
    assert client.get(f"/campaigns/g1/maps/{other_map}/known", headers=OTHER).status_code == 404
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/backend/tests/test_public_projects.py -q -k "stranger or bounded"`
Expected: `test_stranger_sees_public_project_in_list`, `test_stranger_can_edit_maps_of_a_public_project`, `test_stranger_gets_403_…` (gets 404) and `test_campaign_routes_stay_bounded_…` (the `/api` read 404s) FAIL. The two link tests and the private test already pass; they pin behaviour that must not change.

- [ ] **Step 3: Implement `access.py`**

Replace `can_access` and `list_projects`, and add two helpers next to `can_access`:

```python
def is_collaborator(db: DbSession, project: models.Project, user: models.User) -> bool:
    """Owner or member — the people a project actually belongs to. Public
    access doesn't count: it is for using a project, not for tying outside
    systems (campaign links) to it."""
    return project.user_id == user.id or is_member(db, project.id, user)


def can_access(db: DbSession, project: models.Project, user: models.User) -> bool:
    """Member rights: any collaborator, and everyone on a public project."""
    return project.is_public or is_collaborator(db, project, user)


def collaborator_project(
    db: DbSession, project_id: str, user: models.User
) -> models.Project | None:
    proj = db.get(models.Project, project_id)
    if proj is None or not is_collaborator(db, proj, user):
        return None
    return proj
```

```python
def list_projects(db: DbSession, user: models.User) -> list[models.Project]:
    """Every project this user owns, is a member of, or that is public,
    most recent first."""
    member_ids = select(models.ProjectMember.project_id).where(
        models.ProjectMember.user_id == user.id
    )
    rows = db.scalars(
        select(models.Project)
        .where(
            or_(
                models.Project.user_id == user.id,
                models.Project.id.in_(member_ids),
                models.Project.is_public.is_(True),
            )
        )
        .order_by(models.Project.updated_at.desc())
    ).all()
    return list(rows)
```

Update the module docstring's first failure mode to read: `- **Not public and not a collaborator → 404.** Don't leak that a private project or its maps exist.` Then add one paragraph: `A public project gives every signed-in user member rights; campaign linking still needs a collaborator (`is_collaborator`).`

- [ ] **Step 4: Implement `routes/campaigns.py`**

In `link`:

```python
    proj = access.collaborator_project(db, body.project_id, user)
```

and in the re-link check:

```python
        if access.collaborator_project(db, existing_link.project_id, user) is None:
```

In `unlink`:

```python
    if proj is not None and not access.is_collaborator(db, proj, user):
```

- [ ] **Step 5: Run the whole backend suite**

Run: `uv run pytest packages/backend -q`
Expected: the new tests pass, and **exactly these 13** existing tests fail, because they test a stranger against a project that is now public:
`test_campaign_visibility::test_project_campaigns_hidden_without_access`, `test_dsl::test_render_stored_map_404_for_other_user`, `test_maps::test_cross_user_map_access_is_404`, `test_project_io::test_export_requires_ownership`, `test_project_members::test_removing_a_member_revokes_access`, `test_project_members::test_non_member_still_gets_404_on_the_members_list`, `test_project_sessions::test_the_index_is_visible_to_a_member_and_hidden_from_outsiders`, `test_projects::test_other_user_cannot_see_or_touch`, `test_projects::test_library_catalog_requires_ownership`, `test_service_membership::test_service_cannot_reach_an_unlinked_project`, `test_service_membership::test_unlinking_revokes_the_access`, `test_service_membership::test_relinking_to_another_project_moves_the_access`, `test_sessions::test_ownership_enforced`.

If a different set fails, stop and investigate before editing tests.

- [ ] **Step 6: Make those tests use private projects**

They test *private-project* behaviour, which still exists; their projects just need to say so. At each creation site listed under **Files**, add `"is_public": False` to the JSON body, e.g. `test_project_members.py:29`:

```python
    return client.post(
        "/api/projects", json={"name": name, "is_public": False}, headers=OWNER
    ).json()["id"]
```

The same one-key change applies at `test_maps.py:87`, `test_dsl.py:268`, `test_projects.py:51` and `:235`, `test_project_io.py:16`, `test_project_sessions.py:18`, `test_service_membership.py:16`, `test_sessions.py:18` and `test_campaign_visibility.py:154`. Change nothing else in those tests.

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest packages/ -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/backend/src/dungml_backend/access.py packages/backend/src/dungml_backend/routes/campaigns.py packages/backend/tests/
git commit -m "feat(access): public projects give every user member rights; campaign linking stays collaborator-only

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: API — `is_public` and `role` out, owner-only visibility PATCH

**Files:**
- Modify: `packages/backend/src/dungml_backend/schemas.py` (`ProjectOut`, new `ProjectPatchIn`)
- Modify: `packages/backend/src/dungml_backend/routes/projects.py` (`_project_out`, `list_projects`, `get_project`, `update_project`)
- Test: `packages/backend/tests/test_public_projects.py` (append)

**Interfaces:**
- Consumes: `access.is_member`, `access.require_owner`, `access.list_projects` (Task 2).
- Produces: `ProjectOut.is_public: bool`, `ProjectOut.role: Literal["owner", "member", "public"]`, with `shared == (role != "owner")` kept; `PATCH /api/projects/{id}` body `{name?: str, is_public?: bool}`.

- [ ] **Step 1: Write the failing tests** (append)

```python
# ---- Task 3: API ----


def _get(client, pid, h):
    return client.get(f"/api/projects/{pid}", headers=h).json()


def test_role_and_is_public_per_caller(client):
    pid = _public(client)
    mine = _get(client, pid, OWNER)
    assert (mine["role"], mine["is_public"], mine["shared"]) == ("owner", True, False)
    theirs = _get(client, pid, OTHER)
    assert (theirs["role"], theirs["shared"]) == ("public", True)


def test_member_role_on_a_public_project(client):
    pid = _public(client)
    client.get("/api/projects", headers=OTHER)   # provision the second user
    assert client.post(f"/api/projects/{pid}/members",
                       json={"identifier": "@dungeon-daemon-service"}, headers=OWNER).status_code == 201
    assert _get(client, pid, OTHER)["role"] == "member"


def test_list_has_no_duplicates_and_the_strongest_role(client):
    pid = _public(client)
    client.get("/api/projects", headers=OTHER)
    client.post(f"/api/projects/{pid}/members",
                json={"identifier": "@dungeon-daemon-service"}, headers=OWNER)
    rows = [p for p in client.get("/api/projects", headers=OTHER).json() if p["id"] == pid]
    assert len(rows) == 1 and rows[0]["role"] == "member"
    rows = [p for p in client.get("/api/projects", headers=OWNER).json() if p["id"] == pid]
    assert len(rows) == 1 and rows[0]["role"] == "owner"


def test_owner_makes_private_member_keeps_stranger_loses(client):
    pid = _public(client)
    r = client.patch(f"/api/projects/{pid}", json={"is_public": False}, headers=OWNER)
    assert r.status_code == 200 and r.json()["is_public"] is False
    assert client.get(f"/api/projects/{pid}", headers=OTHER).status_code == 404
    client.post(f"/api/projects/{pid}/members",
                json={"identifier": "@dungeon-daemon-service"}, headers=OWNER)
    assert _get(client, pid, OTHER)["role"] == "member"


def test_only_the_owner_changes_visibility(client):
    pid = _public(client)
    r = client.patch(f"/api/projects/{pid}", json={"is_public": False}, headers=OTHER)
    assert r.status_code == 403
    assert _get(client, pid, OWNER)["is_public"] is True


def test_anyone_with_access_can_still_rename(client):
    pid = _public(client)
    r = client.patch(f"/api/projects/{pid}", json={"name": "Renamed"}, headers=OTHER)
    assert r.status_code == 200 and r.json()["name"] == "Renamed"


def test_patch_needs_a_field(client):
    pid = _public(client)
    assert client.patch(f"/api/projects/{pid}", json={}, headers=OWNER).status_code == 422
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/backend/tests/test_public_projects.py -q -k "role or private or visibility or rename or patch"`
Expected: FAIL with `KeyError: 'role'` or `'is_public'`, and the PATCH tests fail because `ProjectIn` requires `name`.

- [ ] **Step 3: Implement `schemas.py`**

At the top of `schemas.py`, add `from typing import Literal` and `from pydantic import model_validator` next to the existing imports. Then:

```python
class ProjectPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    # Owner-only; the route enforces it.
    is_public: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "ProjectPatchIn":
        if self.name is None and self.is_public is None:
            raise ValueError("send name and/or is_public")
        return self
```

In `ProjectOut`, after `owner`:

```python
    is_public: bool = True
    # How the caller reaches the project: owning it, as a member, or only
    # because it is public. `shared` is kept for older clients (role != owner).
    role: Literal["owner", "member", "public"] = "owner"
```

- [ ] **Step 4: Implement `routes/projects.py`**

```python
def _role(db, proj: models.Project, user: models.User) -> str:
    if proj.user_id == user.id:
        return "owner"
    return "member" if access.is_member(db, proj.id, user) else "public"


def _project_out(db, proj: models.Project, user: models.User) -> schemas.ProjectOut:
    role = _role(db, proj, user)
    return schemas.ProjectOut(
        id=proj.id,
        name=proj.name,
        created_at=proj.created_at,
        updated_at=proj.updated_at,
        shared=role != "owner",
        owner=_owner_label(proj),
        is_public=proj.is_public,
        role=role,
    )
```

Pass `db` at every call site: `list_projects` (`_project_out(db, p, user)`), `get_project`, and `update_project`. Then `update_project`:

```python
@router.patch("/{project_id}", response_model=schemas.ProjectOut)
def update_project(
    project_id: str,
    body: schemas.ProjectPatchIn,
    user: CurrentUser,
    db: DbDep,
) -> schemas.ProjectOut:
    proj = _get_owned(db, project_id, user)
    if body.is_public is not None:
        access.require_owner(proj, user)   # 403: visibility is the owner's call
        proj.is_public = body.is_public
    if body.name is not None:
        proj.name = body.name
    db.commit()
    db.refresh(proj)
    return _project_out(db, proj, user)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/backend/tests/test_public_projects.py -q`
Expected: all pass.
Run: `uv run pytest packages/ -q`
Expected: all pass (`test_projects.py::test_rename` still sends `{"name": …}`).

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/dungml_backend/schemas.py packages/backend/src/dungml_backend/routes/projects.py packages/backend/tests/test_public_projects.py
git commit -m "feat(api): projects report is_public and the caller's role; owner-only visibility PATCH

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: MCP server authorizes through `access.py`

**Files:**
- Modify: `packages/mcp/src/dungml_mcp/server.py` (`_owned_project`, `_owned_map`, `_owned_session`, `list_projects`, `delete_project`)
- Test: `packages/mcp/tests/test_server.py` (append)

**Interfaces:**
- Consumes: `access.accessible_project`, `access.can_access`, `access.list_projects` (Task 2).
- Produces: the same helper names and signatures (`_owned_project(db, project_id, user_id)` etc.). The 26 call sites stay untouched; only the rule inside changes. `delete_project` raises `ValueError` for a non-owner.

- [ ] **Step 1: Write the failing tests** (append to `packages/mcp/tests/test_server.py`)

```python
def _someone_elses_project(server, *, public: bool) -> str:
    from dungml_backend import models
    with server._session() as db:
        other = models.User(subject="someone-else", email="else@test")
        db.add(other); db.flush()
        p = models.Project(user_id=other.id, name="theirs", is_public=public)
        db.add(p); db.commit()
        return p.id


def test_public_projects_of_others_are_listed_and_usable(fresh_db):
    s = fresh_db
    pid = _someone_elses_project(s, public=True)
    assert pid in [p["id"] for p in s.list_projects()]
    assert s.list_maps(project_id=pid) == []   # reachable, and it has no maps yet


def test_private_projects_of_others_stay_hidden(fresh_db):
    s = fresh_db
    pid = _someone_elses_project(s, public=False)
    assert pid not in [p["id"] for p in s.list_projects()]
    with pytest.raises(ValueError):
        s.list_maps(project_id=pid)


def test_only_the_owner_deletes_a_public_project(fresh_db):
    s = fresh_db
    pid = _someone_elses_project(s, public=True)
    with pytest.raises(ValueError, match="owner"):
        s.delete_project(project_id=pid)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/mcp/tests/test_server.py -q -k "others or owner_deletes"`
Expected: `test_public_projects_of_others…` FAILs (not listed; `list_maps` raises "not found"), and `test_only_the_owner…` FAILs (raises "not found", which doesn't match "owner").

- [ ] **Step 3: Implement**

Add `from dungml_backend import access` to the server's imports. Replace the three helpers:

```python
def _user(db: DbSession, user_id: str) -> models.User:
    return db.get(models.User, user_id)


def _owned_project(db: DbSession, project_id: str, user_id: str) -> models.Project:
    """A project this user may work on — owner, member or public (access.py)."""
    p = access.accessible_project(db, project_id, _user(db, user_id))
    if p is None:
        raise ValueError(f"project {project_id!r} not found")
    return p


def _owned_map(db: DbSession, map_id: str, user_id: str) -> models.Map:
    m = db.get(models.Map, map_id)
    if m is None or not access.can_access(db, m.project, _user(db, user_id)):
        raise ValueError(f"map {map_id!r} not found")
    return m
```

`_owned_session` stays as is; it goes through `_owned_map`. In `list_projects`, replace the `select` with:

```python
        rows = access.list_projects(db, user)
```

In `delete_project`, after `proj = _owned_project(…)`:

```python
        if proj.user_id != user.id:
            raise ValueError("only the project owner can delete it")
```

Update the `list_projects` docstring to: `"""List the projects the MCP user can work on (own, member, public), newest first."""`

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/mcp -q`
Expected: all pass.
Run: `uv run pytest packages/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add packages/mcp/src/dungml_mcp/server.py packages/mcp/tests/test_server.py
git commit -m "feat(mcp): authorize through access.py — members and public projects, owner-only delete

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Web app — grouping, badges, create option, owner toggle

**Files:**
- Modify: `packages/web/src/lib/types.ts` (`Project`)
- Modify: `packages/web/src/lib/api.ts` (`projects.create`, new `projects.setPublic`)
- Modify: `packages/web/src/routes/ProjectsPage.tsx` (grouping, badge, create checkbox)
- Modify: `packages/web/src/routes/Lists.module.css` (`.sectionHeading`)
- Modify: `packages/web/src/components/ProjectMembers.tsx` (visibility toggle)
- Modify: `packages/web/src/routes/ProjectPage.tsx:314-317` (pass `isPublic`)
- Test: `packages/web/src/components/ProjectMembers.test.tsx` (update + append), `packages/web/src/routes/ProjectsPage.test.tsx` (new)

**Interfaces:**
- Consumes: `ProjectOut.is_public`, `ProjectOut.role`; `PATCH /api/projects/{id}` `{is_public}` (Task 3).
- Produces: `api.projects.create(name: string, isPublic?: boolean)`, `api.projects.setPublic(id: string, isPublic: boolean): Promise<Project>`; `ProjectMembers` prop `isPublic: boolean`.

- [ ] **Step 1: Write the failing tests**

In `ProjectMembers.test.tsx`, every existing mount gains the new required prop. Replace `<ProjectMembers projectId="p1" ` with `<ProjectMembers projectId="p1" isPublic ` (run `sed -i 's/<ProjectMembers projectId="p1" /<ProjectMembers projectId="p1" isPublic /' packages/web/src/components/ProjectMembers.test.tsx`). Then append:

```tsx
test("the owner can make a public project private", async () => {
  vi.spyOn(api.projects.members, "list").mockResolvedValue([]);
  const setPublic = vi
    .spyOn(api.projects, "setPublic")
    .mockResolvedValue({} as never);
  mount(<ProjectMembers projectId="p1" isPublic isOwner owner="me@example.com" />);
  const toggle = await screen.findByRole("checkbox", { name: /public/i });
  expect(toggle).toBeChecked();
  fireEvent.click(toggle);
  await waitFor(() => expect(setPublic).toHaveBeenCalledWith("p1", false));
});

test("a non-owner sees the visibility but cannot change it", async () => {
  vi.spyOn(api.projects.members, "list").mockResolvedValue([]);
  mount(<ProjectMembers projectId="p1" isPublic isOwner={false} owner="me@example.com" />);
  expect(await screen.findByText(/public — everyone who signs in/i)).toBeInTheDocument();
  expect(screen.queryByRole("checkbox", { name: /public/i })).toBeNull();
});
```

Create `packages/web/src/routes/ProjectsPage.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import * as api from "../lib/api";
import type { Project } from "../lib/types";
import { ProjectsPage } from "./ProjectsPage";

afterEach(() => vi.restoreAllMocks());

const base = { created_at: "2026-09-26T12:00:00Z", updated_at: "2026-09-26T12:00:00Z", owner: "gm@x" };
const P = (id: string, role: Project["role"], is_public = true): Project => ({
  ...base, id, name: id, role, is_public, shared: role !== "owner",
});

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><ProjectsPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

test("projects are grouped by how you reach them", async () => {
  vi.spyOn(api.projects, "list").mockResolvedValue([
    P("mine", "owner", false), P("shared-in", "member"), P("everyone", "public"),
  ]);
  mount();
  const mine = await screen.findByRole("region", { name: /mine/i });
  expect(within(mine).getByText("mine")).toBeInTheDocument();
  expect(within(mine).getByText(/private/i)).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: /shared with me/i })).getByText("shared-in")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: /^public$/i })).getByText("everyone")).toBeInTheDocument();
});

test("empty groups are not shown", async () => {
  vi.spyOn(api.projects, "list").mockResolvedValue([P("mine", "owner")]);
  mount();
  await screen.findByRole("region", { name: /mine/i });
  expect(screen.queryByRole("region", { name: /shared with me/i })).toBeNull();
  expect(screen.queryByRole("region", { name: /^public$/i })).toBeNull();
});

test("a public project shows no Delete button", async () => {
  vi.spyOn(api.projects, "list").mockResolvedValue([P("everyone", "public")]);
  mount();
  const pub = await screen.findByRole("region", { name: /^public$/i });
  expect(within(pub).queryByRole("button", { name: /delete/i })).toBeNull();
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd packages/web && npx vitest run src/components/ProjectMembers.test.tsx src/routes/ProjectsPage.test.tsx`
Expected: FAIL. There is no checkbox, no regions, and TypeScript complains that `role`/`is_public` aren't on `Project` (vitest reports the type errors only if type-checking is on, but the queries fail regardless).

- [ ] **Step 3: Implement types and API**

`types.ts`, in `Project`:

```ts
  /** Every signed-in user gets member rights on a public project. */
  is_public: boolean;
  /** How the caller reaches it. `shared` is `role !== "owner"`. */
  role: "owner" | "member" | "public";
```

`api.ts`, in `projects`:

```ts
  create: (name: string, isPublic = true) =>
    request<Project>("POST", "/api/projects", { name, is_public: isPublic }),
  // Owner-only; the backend 403s anyone else.
  setPublic: (id: string, isPublic: boolean) =>
    request<Project>("PATCH", `/api/projects/${id}`, { is_public: isPublic }),
```

- [ ] **Step 4: Implement `ProjectsPage.tsx`**

State for the create form: `const [isPublic, setIsPublic] = useState(true);`. The mutation becomes `mutationFn: ({ n, pub }: { n: string; pub: boolean }) => api.projects.create(n, pub)`, `onCreate` calls `create.mutate({ n: name.trim(), pub: isPublic })`, and `onSuccess` also runs `setIsPublic(true)`. Inside the create `<form>`, before the Create button:

```tsx
                <label className={styles.checkLabel}>
                  <input
                    type="checkbox"
                    checked={isPublic}
                    onChange={(e) => setIsPublic(e.target.checked)}
                  />
                  Public — everyone who signs in can see and edit
                </label>
```

Replace the single `<ul className={styles.list}>…</ul>` with the grouped sections:

```tsx
            <>
              {GROUPS.map(({ role, title }) => {
                const rows = projects.filter((p) => p.role === role);
                if (rows.length === 0) return null;
                const id = `projects-${role}`;
                return (
                  <section key={role} aria-labelledby={id}>
                    <h2 id={id} className={styles.sectionHeading}>{title}</h2>
                    <ul className={styles.list}>
                      {rows.map((p) => (
                        <ProjectRow key={p.id} project={p} />
                      ))}
                    </ul>
                  </section>
                );
              })}
            </>
```

with, at module level:

```tsx
const GROUPS: { role: Project["role"]; title: string }[] = [
  { role: "owner", title: "Mine" },
  { role: "member", title: "Shared with me" },
  { role: "public", title: "Public" },
];
```

In `ProjectRow`, the meta line becomes:

```tsx
          <span className={styles.itemMeta}>
            {project.is_public ? "Public" : "Private"} ·{" "}
            {project.shared ? `${project.owner} · ` : ""}
            Updated {relativeTime(project.updated_at)}
          </span>
```

The Delete button already hides when `project.shared`, and `role: "public"` is shared, so no change is needed there.

`Lists.module.css`, append:

```css
.sectionHeading {
  font-size: 0.95rem;
  font-weight: 600;
  margin: 1.25rem 0 0.5rem;
  color: var(--text-muted, #555);
}
.checkLabel {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.9rem;
}
```

- [ ] **Step 5: Implement `ProjectMembers.tsx`**

Add `isPublic: boolean` to the props (destructure it), then:

```tsx
  const visibility = useMutation({
    mutationFn: (pub: boolean) => api.projects.setPublic(projectId, pub),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (e: unknown) =>
      setError(e instanceof Error ? e.message : "could not change visibility"),
  });
```

Right after the `Owner:` line:

```tsx
      {isOwner ? (
        <label className={styles.visibility}>
          <input
            type="checkbox"
            checked={isPublic}
            disabled={visibility.isPending}
            onChange={(e) => visibility.mutate(e.target.checked)}
          />
          Public — everyone who signs in can see and edit, including deleting maps
        </label>
      ) : (
        <p className={styles.visibility}>
          {isPublic
            ? "Public — everyone who signs in can see and edit"
            : "Private — only the owner and the people it is shared with"}
        </p>
      )}
```

Add to `ProjectMembers.module.css`:

```css
.visibility {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0.25rem 0 0.75rem;
  font-size: 0.9rem;
}
```

`ProjectPage.tsx`, the `<ProjectMembers …>` element gains `isPublic={project?.is_public ?? true}`.

- [ ] **Step 6: Run the web tests and build**

Run: `cd packages/web && npm run test && npm run build`
Expected: all vitest suites pass; the build succeeds with no TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add packages/web/src
git commit -m "feat(web): projects grouped Mine / Shared / Public, public by default, owner toggle

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Docs — CLAUDE.md and README

**Files:**
- Modify: `CLAUDE.md` (section *Projects have members, not just an owner*)
- Modify: `README.md` (backend API surface list)

- [ ] **Step 1: CLAUDE.md**

In *Projects have members, not just an owner*, after the paragraph starting `` `projects.user_id` is still the single owner``, add:

```markdown
**Projects are public by default.** `projects.is_public` gives every signed-in
user member rights — see, edit, create and delete maps, run sessions, rename.
The owner switches it (`PATCH {is_public}`, owner-only → 403). Two kinds are
created private and were set private when the column arrived:
the ttrpg2 service project (ttrpg2 rewrites those maps on every token move)
and each user's *Example: dungml samples* project. `ProjectOut.role` says how
the caller reaches a project: `owner`, `member` or `public`.

**Campaign linking needs a collaborator, not just access.** `link`/`unlink` use
`access.is_collaborator` (owner or member): a public project must not collect
strangers' campaigns, and a link grants the daemon membership.
```

Change the bullet `- no access at all → **404** (don't leak that a project exists)` to `- not public and no access → **404** (don't leak that a private project exists)`.

In the same section, replace `It now reads and creates maps through `/api` like a member.` with `It now reads and creates maps through `/api` like a member — on every public project too, not just linked ones.`

- [ ] **Step 2: README.md**

In *Backend API surface*, change the projects line to:

```markdown
- `GET|POST /api/projects`, `GET|PATCH|DELETE /api/projects/{id}` (projects are
  public by default — every signed-in user gets member rights; `is_public` on
  create, owner-only `PATCH {is_public}`)
```

- [ ] **Step 3: Verify and commit**

Run: `uv run pytest packages/ -q && (cd packages/web && npm run test)`
Expected: all pass.

```bash
git add CLAUDE.md README.md
git commit -m "docs: public projects in CLAUDE.md and README

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
