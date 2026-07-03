# packages/backend/src/dungml_backend/identity.py
"""dungml auth seam — Keycloak OIDC with a static dev mode (Plan 1).

The API depends on IdentityProvider, never on Keycloak directly: tests/dev use
opaque static tokens; prod validates RS256 JWTs from the shared realm. A token
whose `azp` is the service client authenticates as a service principal (the
ttrpg3 M2M path)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from . import config


@dataclass(frozen=True)
class Principal:
    subject: str
    email: str = ""
    roles: tuple[str, ...] = ()
    is_service: bool = False
    username: str = ""
    name: str = ""


class IdentityError(Exception):
    """Token missing, malformed, expired, or unrecognised."""


def principal_from_claims(claims: dict, service_client_id: str) -> Principal:
    """Map OIDC/JWT claims to a Principal. Pure — no network, no token decode."""
    subject = claims.get("sub")
    if not subject:
        raise IdentityError("token has no subject")
    return Principal(
        subject=subject,
        email=claims.get("email", ""),
        roles=tuple(claims.get("realm_access", {}).get("roles", [])),
        is_service=claims.get("azp") == service_client_id,
        username=claims.get("preferred_username", ""),
        name=claims.get("name", ""),
    )


def display_name(p: Principal) -> str:
    """Best human-readable label for a principal, with graceful fallbacks."""
    return p.name or p.username or p.email or p.subject


@runtime_checkable
class IdentityProvider(Protocol):
    def authenticate(self, token: str) -> Principal: ...


class StaticIdentityProvider:
    """Dev/test only. Opaque bearer tokens → principals. No passwords, no network."""

    def __init__(self, tokens: dict[str, Principal] | None = None) -> None:
        self._tokens = tokens or {
            config.settings.dev_token: Principal(
                "dev-user", "dev-user@dungml.local", ("dm",), False,
                username="dev-user", name="Dev User",
            ),
            config.settings.dev_service_token: Principal(
                "@dungeon-daemon-service", "service@dungml.local", (), True
            ),
        }

    def authenticate(self, token: str) -> Principal:
        p = self._tokens.get(token)
        if p is None:
            raise IdentityError("unknown token")
        return p


class KeycloakJWTIdentityProvider:
    """Validates RS256 OIDC JWTs against the realm JWKS. A token whose `azp`
    equals the service client id authenticates as a service principal."""

    def __init__(self, jwks_url: str, issuer: str, audience: str, service_client_id: str) -> None:
        from jwt import PyJWKClient

        self._jwks = PyJWKClient(jwks_url)
        self._issuer = issuer or None
        self._audience = audience or None
        self._service_client_id = service_client_id

    def authenticate(self, token: str) -> Principal:
        import jwt

        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, signing_key.key, algorithms=["RS256"],
                audience=self._audience, issuer=self._issuer,
                options={"verify_aud": self._audience is not None},
            )
        except Exception as exc:
            raise IdentityError(str(exc)) from exc
        return principal_from_claims(claims, self._service_client_id)


def get_identity_provider() -> IdentityProvider:
    s = config.settings
    if s.auth_mode == "keycloak":
        return KeycloakJWTIdentityProvider(
            s.keycloak_jwks_url, s.keycloak_issuer, s.keycloak_audience, s.service_client_id
        )
    return StaticIdentityProvider()
