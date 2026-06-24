"""FastAPI dependencies."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import models
from .db import session_dep
from .identity import IdentityError, Principal, get_identity_provider

DbDep = Annotated[DbSession, Depends(session_dep)]


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authorization.split(" ", 1)[1].strip()


def current_principal(
    db: DbDep, authorization: str | None = Header(default=None)
) -> Principal:
    token = _bearer(authorization)
    try:
        return get_identity_provider().authenticate(token)
    except IdentityError as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def current_user(
    db: DbDep, authorization: str | None = Header(default=None)
) -> models.User:
    """Resolve the principal, then JIT get-or-create the local User by subject."""
    principal = current_principal(db, authorization)
    user = db.scalar(select(models.User).where(models.User.subject == principal.subject))
    if user is None:
        user = models.User(subject=principal.subject, email=principal.email)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
CurrentUser = Annotated[models.User, Depends(current_user)]


def require_service(principal: CurrentPrincipal) -> Principal:
    if not principal.is_service:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "service principal required")
    return principal


CurrentService = Annotated[Principal, Depends(require_service)]
