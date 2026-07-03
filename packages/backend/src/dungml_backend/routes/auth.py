"""Auth routes — identity via Keycloak (OIDC migration). Only /me remains;
registration/login happen at the IdP."""
from __future__ import annotations

from fastapi import APIRouter

from ..deps import CurrentPrincipal
from ..identity import display_name

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def me(principal: CurrentPrincipal) -> dict:
    return {
        "subject": principal.subject,
        "email": principal.email,
        "username": principal.username,
        "name": principal.name,
        "display": display_name(principal),
        "roles": list(principal.roles),
        "is_service": principal.is_service,
    }
