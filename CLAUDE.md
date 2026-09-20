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
- `POST /reveal` `{feature_id}` — discover a node + its visible doors
- `POST /party` `{room_id}` — move the party marker, discovering that node
- `POST /tokens` `{scope: "fog"|"gm"}` — mint an HMAC render grant
- `GET  /info` — `{map_id, session_id}`
- `GET  /render?token=…` — the SVG (no identity dep, so a plain `<img>` works)

`routes/campaigns.py` — `/campaigns/{external_id}/…`. Maps authored *here* in
the editor; an external campaign is linked to a GM-owned Project, and each
campaign carries its own fog on a shared map (`PlaySession` keyed by
`(map_id, external_id)`). `link`/`unlink` are **user**-authorized; everything
else is service-scoped and bounded to linked projects.

`GET /maps/{map_id}/rooms` gives the node graph — map-keyed and
session-independent, because structure is authored truth, not per-campaign.

**Invariant worth protecting:** replacing a map's source must not reset
discovery. Node ids are stable across re-emissions, and ttrpg2 re-pushes its
whole DSL on every token move — if a replace re-fogged the map, the party
would lose its exploration mid-fight. `test_source_preserves_discovery`
pins this.

---

## Running and testing

See README for the full quickstart. In short:

```bash
uv sync                                   # Python workspace (dsl + backend + mcp)
uv run pytest packages/                   # 458 tests — run this before any commit
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
