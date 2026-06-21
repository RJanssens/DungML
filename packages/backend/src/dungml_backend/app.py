"""FastAPI app factory.

All API routes live under `/api`. `/health` stays at the root for
deployment health checks. If the bundled SPA exists at `static/`, it's
served at `/` with a fallback so React Router client routes work.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config
from .db import get_sessionmaker, init_schema
from .library import backfill_core_maps
from .routes import auth, docs, dsl, maps, meta, projects, sessions

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    init_schema()
    # Give every pre-existing project its editable core.dmap.
    session = get_sessionmaker()()
    try:
        backfill_core_maps(session)
    finally:
        session.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="dungml",
        version="0.1.0",
        description="Parse, validate, render, and persist .dmap files.",
        lifespan=_lifespan,
        # Move Swagger UI off `/docs` — that path is owned by the SPA's
        # DSL reference page.
        docs_url="/api-docs",
        redoc_url="/api-redoc",
        swagger_ui_oauth2_redirect_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.settings.cors_origins) or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix="/api")
    api.include_router(auth.router)
    api.include_router(projects.router)
    api.include_router(maps.router)
    api.include_router(dsl.router)
    api.include_router(dsl.map_render_router)
    api.include_router(sessions.router)
    api.include_router(docs.router)
    app.include_router(api)
    app.include_router(meta.router)  # /health at root

    # Single-file embeddables served from fixed paths so consumers can drop in
    # one <script> tag: the map Web Component and the play-view widget. Each
    # needs an explicit route — otherwise the SPA fallback below would shadow
    # the real file with index.html.
    for embed_name in ("dungml-map.js", "dungml-play.js"):
        embed_path = STATIC_DIR / embed_name

        def _make_embed_route(path: Path):
            async def _serve_embed() -> FileResponse:
                return FileResponse(
                    path,
                    media_type="application/javascript",
                    headers={"cache-control": "public, max-age=300"},
                )

            return _serve_embed

        if embed_path.exists():
            app.add_api_route(
                f"/{embed_name}",
                _make_embed_route(embed_path),
                include_in_schema=False,
                response_class=FileResponse,
            )

    if STATIC_DIR.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=STATIC_DIR / "assets"),
            name="assets",
        )

        @app.exception_handler(StarletteHTTPException)
        async def _spa_fallback(request: Request, exc: StarletteHTTPException):
            """For 404s on GETs outside /api, return the SPA index so the
            client router can resolve the route."""
            if (
                exc.status_code == 404
                and request.method == "GET"
                and not request.url.path.startswith("/api")
                and not request.url.path.startswith("/health")
                and INDEX_HTML.exists()
            ):
                return FileResponse(INDEX_HTML)
            # Fall back to FastAPI's default JSON error response.
            from fastapi.exception_handlers import http_exception_handler

            return await http_exception_handler(request, exc)

        @app.get("/", include_in_schema=False)
        async def _root() -> FileResponse:
            return FileResponse(INDEX_HTML)

    return app
