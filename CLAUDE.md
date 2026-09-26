# dungml — CLAUDE.md

A DSL, renderer, FastAPI backend and React editor for tabletop RPG maps.
`README.md` is the developer orientation (layout, quickstart, API surface,
MCP tools) — **read it first and don't duplicate it here.** This file covers
what isn't in the README: who depends on this repo, the invariants that will
break them, and the traps.

---

## This repo has a downstream consumer

**`~/claude/ttrpg2` (the TTRPG campaign system) runs against this backend.**
It is not a library consumer — it talks HTTP to a running `dmap-server`:

| ttrpg2 module | What it calls | Why |
|---|---|---|
| `tools/combat_map.py` | `POST /api/dsl/render` | renders tactical combat maps |
| `tools/dungml_play.py` | the map + campaign contracts (below) | fog of war on its combat tab |

So **the contract routes and `/api/dsl/render` are a public API.** Changing
their shape, auth requirements or response keys breaks a separate project
that is not in this repo's test suite. Grep ttrpg2 before touching them.

### The two contracts

Both are **root-mounted** (not under `/api`) and take a service principal.

`routes/contract.py` — `/maps/{external_id}/…`. One Map + one PlaySession per
external id, lazily provisioned (`contract.get_or_create_map`). The caller
owns the DSL:

- `POST /fragments` — append to the source (caller discovers its map piecemeal)
- `PUT  /source` — **replace** the source (caller re-emits it whole)
- `POST /reveal` `{feature_id}` — discover a node + its visible doors. Takes
  an id, bare name, label, or corridor display name — not just an id — and
  returns `{ok, revealed, room}`, where `room` is the freshly-discovered
  `room_context`, never a bare `{"ok": true}`. 404
  `{error: "unknown room", query, candidates}` if `feature_id` names none or
  several nodes; 409 if the map doesn't parse.
- `POST /party` `{room_id}` — move the party marker, discovering that node.
  Same name/label resolution, same `{ok, party_location, room}` shape, same
  404 (with `candidates`) / 409 as `/reveal`.
- `POST /tokens` `{scope: "fog"|"gm"}` — mint an HMAC render grant
- `GET  /info` — `{map_id, session_id}`
- `GET  /render?token=…` — the SVG (no identity dep, so a plain `<img>` works)

`routes/campaigns.py` — `/campaigns/{external_id}/…`. Maps authored *here* in
the editor; an external campaign is linked to a GM-owned Project, and each
campaign carries its own fog on a shared map (`PlaySession` keyed by
`(map_id, external_id)`). `link`/`unlink` are **user**-authorized; everything
else is service-scoped and bounded to linked projects.

`PUT /campaigns/{external_id}/active` `{map_id}` records which of the linked
project's maps the campaign is playing on. dungml can't know this — the choice
lives in ttrpg2's state — and without it the web app can't point the GM at the
live session. ttrpg2 re-reports it on every probe, so it self-heals.

The per-map session routes mirror `/maps/{external_id}` above (`reveal`,
`party`), plus three the legacy contract doesn't have:

- `GET  /campaigns/{external_id}/maps/{map_id}/rooms/{query}` `?scope=gm|fog`
  — one room's context (`room_context`), resolving `query` against the
  node's id, bare name, label, or corridor display name. `scope` is a
  `Literal["gm", "fog"]`; anything else is a 422. `fog` drops the whole
  `dm_only` key rather than trying to redact inside it. 404
  `{error: "unknown room", query, candidates}` if `query` is ambiguous or
  matches nothing; 409 if the map doesn't parse.
- `GET  /campaigns/{external_id}/maps/{map_id}/known` — the session's whole
  known-map view (`known_map`); 409 if the map doesn't parse.
- `POST /campaigns/{external_id}/maps/{map_id}/reveal` `{feature_id}` /
  `POST .../party` `{room_id}` — same name/label resolution, same
  `{ok, revealed|party_location, room}` shape, same 404 (with `candidates`) /
  409 as the legacy contract's `/reveal` and `/party`. `party` additionally
  clears this campaign's party marker on every *other* linked map
  (`clear_party_elsewhere`) and records this map as the active one
  (`set_active_map`) — the same bookkeeping `PUT /active` does by hand.
- `POST /campaigns/{external_id}/maps/{map_id}/doors`
  `{door?, between?, discovered=true, state?}` — record a found secret door
  and/or a runtime state (opened, forced, locked); the authored map itself
  never changes, only the session. `door` is a door key; `between` is a
  `[node, node]` pair resolved the same way as `rooms/{query}`, used to find
  the door joining them. 404 `{error: "unknown door", door, between}` if
  neither resolves to a real door, or `{error: "ambiguous door", candidates}`
  if `between` matches more than one. → `{ok, door, state, discovered}`.

`GET /maps/{map_id}/rooms` gives the node graph — map-keyed and
session-independent, because structure is authored truth, not per-campaign.
Each entry carries `id`, `name`, `kind`, `label` (falls back to the corridor's
display name, then the bare name), `hidden` (declared inside a hidden layer),
`exits` and `secret_exits` — the latter split out because `exits` only lists
non-concealed doors; a concealed one belongs in `secret_exits` until a
session actually finds it (this route is session-independent, so it can't
know what any one campaign has discovered — it reports the door as *authored*
secret either way).

**"What is secret" lives in one place: the `dungml.room_context` module.**
Its `room_context()` splits a room into `perceived` (boxed text, visible
features, doors the party has found) and `dm_only` (notes, unfound secret
doors, traps, secret features, and the names of rooms beyond perceived exits
whose far side the party hasn't entered — `perceived` gives those exits
`to_label: null`, `dm_only.exit_labels` maps door key to name), and its `node_exits()`/`known_map()` apply
the same discovered-vs-hidden split at the exit-list and whole-map level.
The campaign and legacy contracts above call `room_context()`, the sessions
routes (`routes/sessions.py`) call `node_exits()`, and the MCP server calls
both `node_exits()` and `known_map()` — all three go through this one module rather than
re-deriving exits or secrecy themselves. If a caller needs "what can this
room's occupant see," it belongs here, not a fresh walk of `graph.edges`.

Externally-driven PlaySessions are named `ttrpg2 · {external_id}`
(`contract.campaign_session_name`), and one still called `"party"` is renamed
in passing — the GM's session list used to show several identical `"party"`
rows with no way to tell which one an external campaign was driving. A name
the GM chose is left alone.

Progress figures (`discovered_nodes` vs `total_nodes`) come from
`contract.node_count`, which parses the map and counts graph nodes. It returns
**0 for a map that doesn't parse** — `GET /api/projects/{id}/sessions` spans a
whole project, and one map mid-edit must not 500 the view. The count runs only
for maps that actually have sessions.

**Invariant worth protecting:** replacing a map's source must not reset
discovery. Node ids are stable across re-emissions, and ttrpg2 re-pushes its
whole DSL on every token move — if a replace re-fogged the map, the party
would lose its exploration mid-fight. `test_source_preserves_discovery`
pins this.

### Projects have members, not just an owner

`projects.user_id` is still the single owner, and `project_members` adds
co-access on top. **Every route that reaches a project, its maps, its DSL or
its play sessions authorizes through `access.py`** — `get_project`, `get_map`,
`can_access`, `require_owner` — rather than comparing `user_id` inline.

- no access at all → **404** (don't leak that a project exists)
- access but an owner-only action → **403** (deleting a project, managing
  membership). A member can already see it, so a 404 there would be theatre.

`POST /api/projects/{id}/members` takes a subject *or* an email and 404s if
nobody matches: a typo must not conjure an account.

**Linking a campaign makes the daemon a member of that project**
(`contract.grant_service_access`), and unlinking revokes it unless another
campaign still links there. The service token was always a valid *login* —
`current_user` resolves it like any other subject — it just had no
authorization outside its own project, which is why ttrpg2 once resorted to
writing `dungml.db` directly to add a room. It now reads and creates maps
through `/api` like a member. Member rights only: no project delete, no
membership management. It *can* edit the GM's authored maps; that boundary is
policy in ttrpg2's CLAUDE.md, not mechanism. The GUI labels the row
"campaign service" so the entry isn't mistaken for a person.

**`users.subject` is nullable.** Rows from before the OIDC migration have
none, and `deps.current_user` resolves by subject — so their projects are
unreachable, and with membership being owner-only to manage, nobody can be
granted access either. `adopt.py` is the way out:

```bash
uv run python -m dungml_backend.adopt dev-user   # hand orphaned projects over
```

It transfers every project whose owner has no subject, keeps the old row on
as a member, and repoints that project's campaign links. Idempotent.

---

## Running and testing

See README for the full quickstart. In short:

```bash
uv sync                                   # Python workspace (dsl + backend + mcp)
uv run pytest packages/                   # 695 tests — run this before any commit
uv run dmap-server                        # → http://127.0.0.1:8000
uv run dmap --help                        # DSL CLI (render, validate, renderers)
uv run dmap-mcp                           # stdio MCP server, shares the backend DB
cd packages/web && npm install && npm run test    # vitest
cd packages/web && npm run build:all              # SPA + embeddable widget
```

`packages/web/npm run build` writes into
`packages/backend/src/dungml_backend/static/`, which is **gitignored** — a
fresh clone serves no SPA until you build it. That is expected, and the
backend API works regardless.

**When ttrpg2 is the thing you're testing**, `dmap-server` must be running
and on the branch you think it is. It loads Python at boot, so a checkout
or an edit does nothing until you restart it. A restart is cheap; a
confusing hour of "my fix didn't apply" is not.

---

## Environment

README lists the basics. The auth and render-token settings are newer and
matter for the contracts — all read once at import in `config.py`:

| Variable | Default | Notes |
|---|---|---|
| `DUNGML_DB_URL` | `sqlite:///./dungml.db` | relative to CWD, so *where* you launch matters |
| `DUNGML_AUTH_MODE` | `static` | `static` (opaque dev tokens) or `keycloak` (RS256 JWT) |
| `DUNGML_DEV_TOKEN` | `dev-user` | static mode: bearer → a normal user principal |
| `DUNGML_DEV_SERVICE_TOKEN` | `dev-service` | static mode: bearer → **service** principal |
| `DUNGML_SERVICE_CLIENT_ID` | `dungeon-daemon-service` | keycloak mode: `azp` claim that marks a service |
| `DUNGML_RENDER_SECRET` | `dev-insecure-render-secret` | HMAC key for render tokens |
| `DUNGML_RENDER_TTL` | `43200` (12h) | render-token lifetime |
| `DUNGML_KEYCLOAK_JWKS_URL` / `_ISSUER` / `_AUDIENCE` | — | keycloak mode only |

The defaults are **dev-only**: static mode means anyone who can reach the
port is `dev-user`, and the render secret is a known string. Don't expose
this beyond localhost without `DUNGML_AUTH_MODE=keycloak` and a real
`DUNGML_RENDER_SECRET`.

`identity.py` is the seam — the API depends on `IdentityProvider`, never on
Keycloak directly. Add auth backends there, not in the routes.

---

## Gotchas

**There is no Alembic.** `init_schema()` runs `create_all` at startup, which
creates *missing tables* but never alters existing ones. Any new column on an
existing table must be hand-added to `db.ensure_columns()` or every install
with an older DB will 500 on the routes that touch it. That has already
happened twice (`maps.is_default`, then the contract's `external_id` columns).
**If you add a column, add it to `ensure_columns` in the same commit.**

**`Map.kind` is a derived property, not a column.** It reads the source for a
top-level `map "…"` block: no block → `"library"` (include-only), else
`"map"`. Don't try to query or filter on it in SQL.

**Built-in features live in include libraries, not the parser.** `feature
chest` with no `include` still renders, but as a generic fallback square plus
an *error* diagnostic per feature. The bundled libraries are in
`packages/dsl/src/dungml/includes/`: `core`, `common-dungeon`, `dungeon`,
`crypt`, `city`, `forest`, `outdoor`. `core.dmap` is the one that carries the
everyday shapes. (ttrpg2 works around this by auto-prepending
`include "core.dmap"` — see its CLAUDE.md.)

**Renderers:** `classic-bw` (default), `floorplan`, `hatched`,
`oldschool-blue`. `GET /api/dsl/renderers` is authoritative.

**Themes are separate from renderers.** A renderer is geometry plus a default
theme (`render/theme.py`: `mono`, `paper`, `blue`); `theme NAME` in the map
block swaps the palette. New colours belong in `Theme`, not as literals —
and never recolour by rewriting the finished SVG (that once mangled author
colours and prose).

**"What is in this map" lives in `dungml.walk`.** Top level vs layers vs
nested-in-a-room, hidden-layer filtering and name dedup are decided there;
the renderer, graph, validator, fog stubs, `room_context` and the MCP server
all call it. Door keys (with their `#N` collision suffix) come from
`graph.keyed_doors`. Don't hand-roll a `for layer in dmap.layers` loop — the
copies drifted before.

**SVG ids and CSS are namespaced per drawing.** Several maps share one page
(scenario, print, GM + fog), so every id goes through `ctx._id(...)` and the
stylesheet is scoped to the root `<svg>`'s `dm-<hash>` class. Keep element
classes as they are — the editor matches `class === "floor"` exactly.

**Fog of war is a pure function.** `graph.fog_of_war` prunes a `DungeonMap` to
the discovered subset and returns a fully valid map, so *any* renderer draws
fog for free with no renderer changes. `play.render_fogged` wraps it and adds
the party marker plus the corridor fade stubs. Keep that property — resist
pushing fog logic into renderers.

**Secret features are stripped from the players' view**, per-instance
(`secret`) or per-type (a `feature_def` marked `secret`, e.g. traps in
`core.dmap`). `full=True` (the GM view) skips `fog_of_war` entirely and so
shows them. If you add a new kind of GM-only content, teach `fog_of_war` to
strip it — otherwise it leaks into the fogged render.

---

## Branch topology

This repo has **two unrelated histories**, which is deliberate and will look
wrong if you don't know:

- `main` / `local-may-wip` — the original 7-commit May line. `local-may-wip`
  holds that machine's last working tree (a `start.sh`, a configurable Vite
  proxy target). Root commit `da2cf06`.
- `summersong-main` — the real line of development, 80 commits, fetched from
  the `summersong` remote (`raf@192.168.86.29:roleplaying/dungml`). Root
  commit `3cf16ac`. **This is the one to build on.**

`git merge` across the two will fight you (`--allow-unrelated-histories`,
whole-tree conflicts). Port individual changes across instead.

Remotes: `summersong` (the authoritative host) and `gitea`
(`ssh://git@192.168.86.29:2222/raf/dungml.git`, backup — SSH key auth on
port **2222**, not 22).

`dungml.db` is gitignored. The working DB came from summersong and holds real
projects; an older, incompatible-schema copy is kept as
`dungml.db.local-old-schema.bak.*`.
