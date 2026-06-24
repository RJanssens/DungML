"""current_principal validates the token; current_user JIT-provisions a User."""
import pytest
from fastapi import HTTPException

from dungml_backend import models
from dungml_backend.deps import current_principal, current_user


def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("DUNGML_DB_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("DUNGML_AUTH_MODE", "static")
    from dungml_backend import config, db
    config.reload_settings(); db.reset_engine(); db.init_schema()
    return next(db.session_dep())


def test_current_principal_rejects_missing_token(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    with pytest.raises(HTTPException):
        current_principal(db, authorization=None)


def test_current_user_jit_provisions_once(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    u1 = current_user(db, authorization="Bearer dev-user")
    u2 = current_user(db, authorization="Bearer dev-user")
    assert u1.subject == "dev-user"
    assert u1.id == u2.id  # same row reused, not duplicated
    assert db.query(models.User).filter_by(subject=u1.subject).count() == 1
