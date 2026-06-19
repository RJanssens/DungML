# dungml

A DSL, backend, and web editor for tabletop RPG map layout — dungeons, buildings, and outdoor terrain.

## Layout

```
packages/
  dsl/       # Grammar, parser, semantic model, validator, renderer ABC + built-ins
  backend/   # FastAPI service (P3)
  web/       # React + Monaco editor (P4)
samples/     # Canonical .dmap files
docs/        # DSL reference
```

## Current phase

**P4 — web editor** (React + Monaco SPA with live preview, served by the backend).

## Layout

```
packages/
  dsl/       # Grammar, parser, semantic model, validator, renderer ABC + classic-bw
  backend/   # FastAPI service (auth, projects, maps, DSL API)
  web/       # React + Monaco editor SPA
  mcp/       # MCP server (project/map CRUD, render, play-session pathfinding)
samples/     # Canonical .dmap files
```

## Quickstart

```bash
# Backend + DSL:
uv sync
uv run pytest packages/

# Web SPA:
cd packages/web && npm install

# Build the SPA into the backend's static dir + start the server (single-process):
cd packages/web && npm run build
cd ../.. && uv run dmap-server
# → http://127.0.0.1:8000
```

### Local dev with HMR

In one terminal, run the backend:

```bash
uv run dmap-server
```

In another, run Vite with API proxy:

```bash
cd packages/web && npm run dev
# → http://127.0.0.1:5173
```

### Try the bundled samples

Once you're signed in, click **Import samples** on the projects page to
get a project containing every `.dmap` file in `samples/`:

- **Quickstart** — start here. Two rooms, one corridor, a handful of
  doors and a window, in ~50 lines that lean heavily on default values.
- **Miller's Cottage** — small building (rooms, doors, windows)
- **Crypt of Saint Vellis** — dungeon with corridors, arcs, hidden layer
- **The Sunken Library of Cael Voren** — large 100×70 map exercising
  every DSL feature (nine rooms across rect / polygon / boundary-with-arc
  shapes, line + arc corridors, five custom feature_defs, eighteen doors
  of every type/state, eight windows, and a hidden layer)
- **The Black Hare Inn** — ground floor of a wayhouse; rich
  per-feature descriptions and DM notes designed to flex the
  print/PDF view
- **Goblin Warren of the Broken Tooth** — five irregular cave
  chambers connected by twisty corridors; uses the `hatched`
  renderer's halo-only style and a hidden trap layer

### CLI shortcuts

```bash
uv run dmap render samples/crypt.dmap -o crypt.svg
uv run dmap render samples/sunken_library.dmap -o sunken.svg
uv run dmap validate samples/cottage.dmap
uv run dmap renderers
```

### Backend API surface (all under `/api`)

- `POST /api/auth/register | /api/auth/login | /api/auth/logout`, `GET /api/auth/me`
- `GET|POST /api/projects`, `GET|PATCH|DELETE /api/projects/{id}`
- `GET|POST /api/projects/{id}/maps`, `GET|PUT|DELETE /api/maps/{id}`
- `POST /api/dsl/parse | /api/dsl/validate | /api/dsl/render` (stateless)
- `GET /api/maps/{id}/render | /api/maps/{id}/validate` (stored-map convenience)
- `GET /health`, `GET /api/dsl/renderers`

OpenAPI docs at `/api-docs` once the server is running. The DSL reference is at `/docs`.

### MCP server (`dmap-mcp`)

```bash
uv run dmap-mcp        # stdio MCP server, shares the backend DB
```

Exposes project/map CRUD + render/validate, plus:

- **Structured authoring** — `add_room` / `add_corridor` / `add_door` grow
  a map by describing geometry relative to what's already there ("a 6×6
  room east of `room.hall`"); placement is computed server-side, grid
  bounds auto-grow, and edits are re-validated before saving. Lets a map
  be built up from a starting room rather than authored all at once.
- **Play-sessions** — a session tracks which rooms/corridors a party has
  discovered, which doors they've found, the live state of those doors,
  and the party's location, as a runtime overlay that never mutates the
  authored `.dmap`. The connectivity graph (rooms/corridors as nodes,
  doors as edges) is derived from the map on demand, so `get_exits`,
  `find_path` (discovery-aware or full-topology), and fog-of-war
  `render_session` run server-side.

Authoring and play-session tools share a `discover_in_session` flag, so a
party can build the map as it explores. See the "Connectivity graph and
pathfinding" section of the DSL reference for details.

### Environment

- `DUNGML_DB_URL` — SQLAlchemy URL (default `sqlite:///./dungml.db`)
- `DUNGML_TOKEN_TTL` — session lifetime in seconds (default 14d)
- `DUNGML_CORS_ORIGINS` — comma-separated origins (default `*`)
- `DUNGML_HOST` / `DUNGML_PORT` / `DUNGML_RELOAD` — uvicorn options
