"""Uvicorn entrypoint — `dmap-server`."""
from __future__ import annotations

import os

import uvicorn

from .app import create_app

app = create_app()


def run() -> None:
    ssl_certfile = os.environ.get("DUNGML_SSL_CERTFILE")
    ssl_keyfile = os.environ.get("DUNGML_SSL_KEYFILE")
    uvicorn.run(
        "dungml_backend.main:app",
        host=os.environ.get("DUNGML_HOST", "127.0.0.1"),
        port=int(os.environ.get("DUNGML_PORT", "8000")),
        reload=bool(os.environ.get("DUNGML_RELOAD", "")),
        ssl_certfile=ssl_certfile or None,
        ssl_keyfile=ssl_keyfile or None,
    )


if __name__ == "__main__":
    run()
