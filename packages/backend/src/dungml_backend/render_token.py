# packages/backend/src/dungml_backend/render_token.py
"""Map-scoped HMAC render tokens (map contract). A token grants per-map render
(scope gm|fog), independent of identity — the player widget/<img> uses it. Signed
with the dev/config render secret; carries an expiry and the external_id it's for."""
from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256

from . import config


class TokenError(Exception):
    """Render token missing, malformed, tampered, expired, or for another map."""


def _sig(payload: str) -> str:
    key = config.settings.render_secret.encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), sha256).hexdigest()


def mint(external_id: str, scope: str, *, now: int | None = None) -> str:
    if scope not in ("gm", "fog"):
        raise TokenError(f"bad scope: {scope!r}")
    exp = (now if now is not None else int(time.time())) + config.settings.render_ttl_seconds
    payload = f"{external_id}.{scope}.{exp}"
    raw = f"{payload}.{_sig(payload)}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def verify(token: str, external_id: str, *, now: int | None = None) -> str:
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        ext, scope, exp_s, sig = raw.rsplit(".", 3)
    except Exception as e:
        raise TokenError("malformed token") from e
    payload = f"{ext}.{scope}.{exp_s}"
    if not hmac.compare_digest(sig, _sig(payload)):
        raise TokenError("bad signature")
    if ext != external_id:
        raise TokenError("token is for a different map")
    if int(exp_s) <= (now if now is not None else int(time.time())):
        raise TokenError("token expired")
    return scope
