"""Runtime configuration.

Reads from environment variables on import:

- `DUNGML_DB_URL` — SQLAlchemy URL. Defaults to a local file
  `dungml.db` next to the working directory.
- `DUNGML_TOKEN_TTL` — session token lifetime in seconds. Default 14d.
- `DUNGML_CORS_ORIGINS` — comma-separated list of CORS origins for the
  web editor. Default: `*` (permissive — fine for local dev only).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_url: str
    token_ttl_seconds: int
    cors_origins: tuple[str, ...]
    auth_mode: str
    keycloak_jwks_url: str
    keycloak_issuer: str
    keycloak_audience: str
    service_client_id: str
    dev_token: str
    dev_service_token: str


def _load() -> Settings:
    return Settings(
        db_url=os.environ.get("DUNGML_DB_URL", "sqlite:///./dungml.db"),
        token_ttl_seconds=int(os.environ.get("DUNGML_TOKEN_TTL", 14 * 24 * 3600)),
        cors_origins=tuple(
            o.strip() for o in os.environ.get("DUNGML_CORS_ORIGINS", "*").split(",") if o.strip()
        ),
        auth_mode=os.environ.get("DUNGML_AUTH_MODE", "static"),
        keycloak_jwks_url=os.environ.get("DUNGML_KEYCLOAK_JWKS_URL", ""),
        keycloak_issuer=os.environ.get("DUNGML_KEYCLOAK_ISSUER", ""),
        keycloak_audience=os.environ.get("DUNGML_KEYCLOAK_AUDIENCE", "dungml-api"),
        service_client_id=os.environ.get("DUNGML_SERVICE_CLIENT_ID", "dungeon-daemon-service"),
        dev_token=os.environ.get("DUNGML_DEV_TOKEN", "dev-user"),
        dev_service_token=os.environ.get("DUNGML_DEV_SERVICE_TOKEN", "dev-service"),
    )


settings = _load()


def reload_settings() -> Settings:
    """Re-read env (test helper)."""
    global settings
    settings = _load()
    return settings
