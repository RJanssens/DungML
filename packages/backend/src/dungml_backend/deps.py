"""FastAPI dependencies."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from . import models
from .auth import lookup_session
from .db import session_dep

DbDep = Annotated[DbSession, Depends(session_dep)]


def current_user(
    db: DbDep,
    authorization: str | None = Header(default=None),
) -> models.User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    sess = lookup_session(db, token)
    if sess is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return sess.user


CurrentUser = Annotated[models.User, Depends(current_user)]
