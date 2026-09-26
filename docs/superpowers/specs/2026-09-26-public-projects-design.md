# Public projects

**Date:** 2026-09-26
**Status:** Approved — approach A, full member rights, and both exceptions

## Problem

Today a project is reachable only by its owner (`projects.user_id`) and its
members (`project_members`). Everything else is a 404. In practice nearly every
project on this server is meant to be shared: the user's words were *"we
generally don't need to make them private."* Sharing one project at a time
through the members list is friction for the common case.

Goal: a project can be **public**, which gives **every signed-in user member
rights** on it. New projects default to public, existing projects become
public, and the owner can switch a project to private.

## What "public" means (approved)

Every authenticated principal — every user, and the ttrpg2 service principal —
gets exactly the rights a member has today on a public project:

- see it in the projects list; open, render and validate its maps; see its
  sessions, campaigns and members list;
- edit, create, rename **and delete maps**, add library files, run play
  sessions, rename the project.

Still **owner-only** (403 for a non-owner who can see the project):

- delete the project;
- manage membership;
- **switch it between public and private** (new).

A private project behaves exactly as today: no access → 404, owner-only → 403.

Out of scope: anonymous (unauthenticated) access, a read-only visibility,
per-map visibility, audit history or undo.

## Approach (A, approved)

A boolean column checked in the one place authorization already lives,
`access.py`. No route-by-route changes.

Alternatives considered and rejected: a `visibility` enum (room for a
read-only mode we don't need yet), and an implicit "everyone" member row
(pollutes the members list and `is_member`).

## Design

### Data

`projects.is_public BOOLEAN NOT NULL`, model default `True`.

There is no Alembic, so `db.ensure_columns()` adds it to existing DBs in the
same commit (see CLAUDE.md, *Gotchas*):

```sql
ALTER TABLE projects ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT 1   -- `true` on Postgres
```

The `DEFAULT` makes every existing row public on first boot, as approved.
Straight after adding the column — and **only** in that branch, so it runs
exactly once — `ensure_columns` sets the two exceptions below back to private.
Running it on every boot would undo an owner who later made one of them
public.

### Where projects are created

| Site | `is_public` |
|---|---|
| `POST /api/projects` | body's `is_public`, default `true` |
| `POST /api/projects/import` (zip) | `true` |
| MCP `create_project` | `true` |
| `contract.py` service project (`_SERVICE_PROJECT`) | **`false`** — see below |
| example samples project (`EXAMPLE_PROJECT_NAME`) | **`false`** — see below |

### Exceptions (approved)

These two refine "new and existing projects are public" (confirmed 2026-09-26):

1. **The ttrpg2 service project stays private.** The legacy `/maps/{external_id}`
   contract provisions maps into the service principal's own project, and
   ttrpg2 re-emits their whole DSL on every token move (`PUT /source`). If the
   project were public, any user could edit or delete a map that ttrpg2 treats
   as its own, and the next push would silently overwrite their edit. Nothing
   is gained: those maps are machine-generated combat maps.
2. **Each user's "Example: dungml samples" project stays private.** *Import
   samples* creates one per user, so if public, every user's list would show
   one identical copy per user who ever clicked the button.

Both are ordinary projects otherwise; their owner can still make them public.

### Authorization (`access.py`)

```python
def is_collaborator(db, project, user) -> bool:   # today's can_access
    return project.user_id == user.id or is_member(db, project.id, user)

def can_access(db, project, user) -> bool:
    return project.is_public or is_collaborator(db, project, user)
```

- `accessible_project`, `get_project`, `get_map`: unchanged; they inherit
  public access through `can_access`.
- `list_projects`: `owner OR member OR is_public`, still newest first.
- `require_owner`: unchanged.
- The module docstring changes: "no access → 404" now reads "not public and
  not a collaborator → 404".

**Campaign linking stays collaborator-only.** `routes/campaigns.py` `link`
and `unlink` switch from `accessible_project`/`can_access` to
`is_collaborator`, keeping today's 404 for everyone else. Otherwise any user
could link their ttrpg2 campaign to someone else's public project. Linking
also makes the service principal a member (`contract.grant_service_access`),
so it would grant a membership that nobody on the project asked for.

**The service principal** gains member rights on every public project through
`/api` (it resolves through `current_user` like anyone else). The
service-scoped `/campaigns/{external_id}/…` routes stay bounded to the linked
project (`contract.map_in_link`), so unchanged. Editing outside its linked
projects remains a ttrpg2 policy matter, as documented in CLAUDE.md today.

### MCP server

`packages/mcp/src/dungml_mcp/server.py` has its own owner-only checks
(`_owned_project`, `_owned_map`, `_owned_session`: `p.user_id != user_id`).
They predate members, so MCP already ignores memberships. They switch to
`access.get_project` / `access.get_map` / `access.can_access`, so MCP sees
member **and** public projects, the same as the API. Its project listing uses
`access.list_projects`.

### API

`ProjectOut` gains:

- `is_public: bool`
- `role: "owner" | "member" | "public"`: how the caller reaches it. An owner
  who is also listed as a member is `owner`; a member of a public project is
  `member`.

`shared` stays, for compatibility (`role != "owner"`).

`POST /api/projects` accepts an optional `is_public` (default `true`).

`PATCH /api/projects/{id}` takes a new `ProjectPatchIn {name?, is_public?}`.
Renaming stays a member right. Changing `is_public` is owner-only → 403.
Sending neither field → 422.

### Web app

- **Projects page** — three sections: *Mine*, *Shared with me*, *Public*
  (`role`). Empty sections are hidden. Each row gets a small *Public* or
  *Private* badge.
- **Project page, People panel** — the owner gets a toggle: *Public — everyone
  who signs in can see and edit* / *Private — only you and the people you
  share with*. Others see the current state as text. Members sharing stays as
  it is; on a public project it still matters, because a member keeps access
  if the owner makes the project private.
- New projects: the create dialog shows the toggle, defaulting to public.

### Docs

- CLAUDE.md, *Projects have members, not just an owner*: add public projects,
  the collaborator-only linking rule, and the two private exceptions; restate
  the 404 rule.
- README API list: `is_public` on create/patch.

## Testing

Backend (`packages/backend/tests`):

- a stranger sees a public project in the list, can open/render/edit its
  maps, and gets **403** on delete, members add/remove and `is_public` change;
- a stranger gets **404** on everything for a private project (today's
  behaviour, regression);
- the owner flips public ↔ private; a member keeps access after private;
- `role` / `shared` / `is_public` values for owner, member and stranger;
- `link` to a public project by a non-collaborator → 404; by a member → ok;
- `ensure_columns` on a pre-column DB: the column is added, ordinary projects
  are public, the service and example projects are private, and a second run
  changes nothing (including after an owner made one of them public);
- `POST /api/projects` default and explicit `is_public: false`; the contract
  and samples paths create private projects.

MCP (`packages/mcp/tests`): public and member projects are listed and editable
through the tools; a private stranger project is not.

Web (vitest): the projects page groups by `role`; the toggle renders only for
the owner.

Existing suites stay green (572 tests on this branch).

## Risks

- **Anyone can delete maps in a public project.** This follows from "full
  member rights" and there is no undo. Accepted; worth a line in the web
  toggle's help text.
- **A private project stays visible until the page reloads** for a stranger
  who already had it open. Their next request gets a 404. Acceptable.
- **ttrpg2**: checked 2026-09-26. `tools/` calls only `/api/dsl/render`, the
  `/maps/{external_id}` contract and `/campaigns/{external_id}/…`. None of these
  change here; `ProjectOut`'s new fields are additive and ttrpg2 doesn't read
  it. Linking is done by a user in the web app, so the collaborator-only rule
  doesn't affect the daemon. Re-grep before merge, per CLAUDE.md.
