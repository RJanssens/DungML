"""/auth — register, login, logout, current user."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select

from .. import auth, models, schemas
from ..deps import CurrentUser, DbDep

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.TokenOut, status_code=201)
def register(body: schemas.RegisterIn, db: DbDep) -> schemas.TokenOut:
    existing = db.scalar(select(models.User).where(models.User.email == body.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email already registered",
        )
    user = models.User(
        email=body.email, password_hash=auth.hash_password(body.password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = auth.issue_token(db, user)
    return schemas.TokenOut(token=token, user=schemas.UserOut.model_validate(user))


@router.post("/login", response_model=schemas.TokenOut)
def login(body: schemas.LoginIn, db: DbDep) -> schemas.TokenOut:
    user = db.scalar(select(models.User).where(models.User.email == body.email))
    if user is None or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )
    token = auth.issue_token(db, user)
    return schemas.TokenOut(token=token, user=schemas.UserOut.model_validate(user))


@router.post("/logout", status_code=204)
def logout(
    db: DbDep,
    authorization: str | None = Header(default=None),
) -> None:
    """Best-effort logout: revoke the bearer token if present and valid.

    Returns 204 even on missing/invalid tokens so clients can call this
    idempotently without leaking whether a token was active.
    """
    if authorization and authorization.lower().startswith("bearer "):
        auth.revoke_token(db, authorization.split(" ", 1)[1].strip())


@router.get("/me", response_model=schemas.UserOut)
def me(user: CurrentUser) -> models.User:
    return user
