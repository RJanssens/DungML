/*
 * dungml — C4 architecture
 *
 * Structurizr DSL describing the system: a declarative DSL for tabletop
 * RPG maps with a parser/renderer library, a FastAPI backend, a web
 * editor, a Model Context Protocol server, and a CLI. Two external
 * consumers are shown: a human user authoring maps in the web GUI, and
 * an LLM client (Claude / IDE) driving the MCP server. A second
 * software system (TTRPG2) consumes dungml's HTTP API for tactical
 * combat maps.
 *
 * Render with: structurizr-cli or https://structurizr.com/dsl
 */

workspace "dungml" "DSL, renderer, and authoring stack for TTRPG maps" {

    !identifiers hierarchical

    model {

        // ── People ─────────────────────────────────────────────────────────
        dm = person "Dungeon Master" {
            description "Authors maps in the web editor; runs sessions in TTRPG2."
        }
        llm = person "LLM client" {
            description "Claude Desktop / IDE / agent connecting to the MCP server."
        }

        // ── Adjacent system (consumer) ─────────────────────────────────────
        ttrpg2 = softwareSystem "TTRPG2" "AD&D 2e session-management server (separate repo, ~/claude/ttrpg2)." "External" {
            ttrpg2_combat = container "combat_map tool" "Combat-session tool that POSTs .dmap source to dungml's render API and stores the SVG in combat_state.json." "Python · MCP tool"
            ttrpg2_dash   = container "Flask dashboard" "Serves /combat — renders the dungml SVG on a canvas, overlays initiative tokens." "Flask · Vanilla JS"
        }

        // ── dungml ─────────────────────────────────────────────────────────
        dungml = softwareSystem "dungml" "Parser, validator, and renderer for the .dmap DSL, plus storage + auth + a Monaco-based editor." {

            dsl = container "DSL library" "Lark-based parser, Pydantic semantic model, classic-bw / floorplan / hatched renderers, scenario renderer. Imported by every other container." "Python (packages/dsl)" {
                parser    = component "parser"        "grammar.lark + Lark Earley transformer. Produces DungeonMap or Scenario." "Python · Lark"
                model     = component "model"         "Typed semantic tree: Room, Corridor, Door, Window, Marker, Slice, FeatureDef, FeatureInstance, Layer, Scenario." "Python · Pydantic"
                geometry  = component "geometry"      "Wall enumeration, door cuts, three-point arcs, shared edges." "Python"
                validator = component "validator"     "Cross-references, bounds, includes resolution diagnostics." "Python"
                builtins  = component "builtins"      "22 built-in feature glyphs (pillar, chest, altar, …) and the marker palette." "Python"
                renderer  = component "classic-bw renderer" "Emits SVG — rooms, walls (with door/window slots cut), corridors, slices, doors, windows, features, markers, labels, legend." "Python"
                hatched   = component "hatched renderer" "Subclass — replaces flat floor fill with a hatched halo around explorable space." "Python"
                scenrend  = component "scenario renderer" "Bundles boxed text + DM notes + each referenced map's SVG into a self-contained HTML document." "Python"
            }

            cli = container "dmap CLI" "`dmap render`, `dmap validate`, `dmap render-scenario`, `dmap renderers` — terminal entry point bundled with the DSL package." "Python · argparse (packages/dsl)"

            backend = container "Backend API" "FastAPI service. Auth (scrypt + session tokens), projects + maps CRUD, stateless DSL parse/validate/render, SPA static hosting." "Python · FastAPI · Uvicorn (packages/backend)" {
                auth_routes     = component "auth routes"     "POST /api/auth/{register,login,logout}, GET /api/auth/me." "FastAPI router"
                projects_routes = component "projects routes" "GET/POST /api/projects, /import-samples, etc." "FastAPI router"
                maps_routes     = component "maps routes"     "GET/POST /api/projects/{id}/maps, GET/PUT/DELETE /api/maps/{id}." "FastAPI router"
                dsl_routes      = component "DSL routes"      "POST /api/dsl/parse|validate|render. Stored-map variants at /api/maps/{id}/render|validate." "FastAPI router"
                docs_routes     = component "docs routes"     "Serves docs/dsl.md and other reference content to the editor." "FastAPI router"
                samples_loader  = component "samples loader"  "On import scans samples/ for .dmap files; skips scenarios and include-only libraries." "Python"
                spa_static      = component "SPA static host" "Mounts /assets, serves /index.html with SPA fallback, serves /dungml-map.js." "FastAPI StaticFiles"
            }

            db = container "Project DB" "User accounts, session tokens, projects, maps. One row per stored map." "SQLite (default: ./dungml.db)" {
                tags "Database"
            }

            web = container "Web editor (SPA)" "Live-preview Monaco editor — split pane DSL + rendered SVG. Pulls feature/glyph reference from /api/dsl/* and /api/docs/dsl." "TypeScript · React · Vite (packages/web)"

            component_js = container "dungml-map.js component" "Framework-free Web Component (<dungml-map>) — embeds rendered maps in any HTML page. Hot-served by the backend at /dungml-map.js." "Vanilla JS · Custom Elements"

            mcp = container "MCP server" "FastMCP stdio server exposing project/map CRUD + render + validate as MCP tools to LLM clients. Re-uses the backend's ORM + SQLite." "Python · MCP SDK (packages/mcp)" {
                tool_list = component "list/create/delete project tools"    "list_projects, create_project, delete_project." "MCP tool"
                tool_maps = component "map CRUD tools"                       "list_maps, create_map, get_map, update_map, delete_map." "MCP tool"
                tool_rend = component "render/validate tools"                "render_map, validate_source, list_renderer_names." "MCP tool"
                mcp_user  = component "MCP-owner bootstrap"                  "Auto-provisions a single 'mcp@local' user on first run; all MCP-owned data lives under that user." "Python"
            }

            samples = container "Bundled samples" "Six canonical .dmap files: quickstart, cottage, crypt, sunken_library, goblin_warren, bramblefen overland; plus the bramblefen scenario." "Files (samples/)" {
                tags "Filesystem"
            }
        }

        // ── Relationships — people to system ────────────────────────────
        dm -> dungml.web                    "Authors and previews maps in"
        dm -> ttrpg2                        "Runs combat sessions in"
        llm -> dungml.mcp                   "Drives via Model Context Protocol (stdio)"

        // ── Relationships — within dungml ───────────────────────────────
        dungml.web        -> dungml.backend     "Calls /api/* (auth, projects, maps, dsl/render)" "JSON over HTTPS"
        dungml.backend    -> dungml.db          "Reads/writes projects + maps" "SQLAlchemy"
        dungml.backend    -> dungml.dsl         "Parses, validates, renders" "Python import"
        dungml.mcp        -> dungml.db          "Reads/writes via shared ORM (same SQLite file)" "SQLAlchemy"
        dungml.mcp        -> dungml.dsl         "Parses + renders" "Python import"
        dungml.cli        -> dungml.dsl         "Parses + renders" "Python import"
        dungml.backend    -> dungml.samples     "Loads on import-samples" "filesystem"
        dungml.component_js -> dungml.backend   "POST /api/dsl/render, GET /api/maps/{id}/render"

        // ── Relationships — TTRPG2 ↔ dungml ─────────────────────────────
        ttrpg2.ttrpg2_combat -> dungml.backend  "POST /api/dsl/render (stateless)" "HTTP+JSON"
        ttrpg2.ttrpg2_dash   -> dungml.component_js "Embeds <dungml-map> for inline live preview" "HTTP"

        // CLI invocations
        dm -> dungml.cli                       "`dmap render`, `dmap render-scenario` from terminal"
    }

    views {

        // ── System Landscape — biggest picture ─────────────────────────
        systemLandscape "Landscape" {
            include *
            autolayout lr
            description "All actors and systems."
        }

        // ── System Context — dungml among its users/consumers ──────────
        systemContext dungml "Context" {
            include *
            autolayout lr
            description "Who and what talks to dungml."
        }

        // ── Containers inside dungml ───────────────────────────────────
        container dungml "Containers" {
            include *
            autolayout lr
            description "The five runtime containers and the on-disk samples directory."
        }

        // ── Components inside each major container ─────────────────────
        component dungml.dsl "DSL-Components" {
            include *
            autolayout lr
            description "Inside the DSL library: parser → model → renderers."
        }

        component dungml.backend "Backend-Components" {
            include *
            autolayout lr
            description "FastAPI routers and adjacent helpers."
        }

        component dungml.mcp "MCP-Components" {
            include *
            autolayout lr
            description "FastMCP tools exposed to LLM clients."
        }

        // ── Visual style ───────────────────────────────────────────────
        styles {
            element "Person" {
                background "#08427b"
                color "#ffffff"
                shape Person
            }
            element "Software System" {
                background "#1168bd"
                color "#ffffff"
            }
            element "External" {
                background "#999999"
                color "#ffffff"
            }
            element "Container" {
                background "#438dd5"
                color "#ffffff"
            }
            element "Component" {
                background "#85bbf0"
                color "#000000"
            }
            element "Database" {
                shape Cylinder
                background "#7b4814"
                color "#ffffff"
            }
            element "Filesystem" {
                shape Folder
                background "#8b6914"
                color "#ffffff"
            }
        }
    }
}
