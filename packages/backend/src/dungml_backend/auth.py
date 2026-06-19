"""Password hashing + session token management.

- Passwords are hashed with `hashlib.scrypt` (NIST-recommended, stdlib).
  The stored hash is `scrypt$N$r$p$salt_hex$hash_hex` so parameters are
  embedded for forward compatibility.
- Session tokens are 32 random bytes (hex-encoded) stored in the
  `sessions` table along with `user_id` and `expires_at`.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import config, models

# scrypt parameters — chosen for ~50ms/hash on a modern laptop.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n_s, r_s, p_s, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    try:
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt, n=n, r=r, p=p, dklen=len(expected),
    )
    return hmac.compare_digest(dk, expected)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def issue_token(db: DbSession, user: models.User) -> str:
    token = secrets.token_hex(32)
    expires = _utcnow() + timedelta(seconds=config.settings.token_ttl_seconds)
    db.add(models.Session(token=token, user_id=user.id, expires_at=expires))
    db.commit()
    return token


def lookup_session(db: DbSession, token: str) -> models.Session | None:
    """Return an active session for `token`, or None if missing/expired."""
    sess = db.get(models.Session, token)
    if sess is None:
        return None
    if sess.expires_at <= _utcnow():
        db.delete(sess)
        db.commit()
        return None
    return sess


def revoke_token(db: DbSession, token: str) -> bool:
    sess = db.get(models.Session, token)
    if sess is None:
        return False
    db.delete(sess)
    db.commit()
    return True
