import pytest
from fastapi import HTTPException

from dungml_backend import contract, models
from dungml_backend.deps import require_service
from dungml_backend.identity import Principal


def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("DUNGML_DB_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("DUNGML_AUTH_MODE", "static")
    from dungml_backend import config, db
    config.reload_settings(); db.reset_engine(); db.init_schema()
    return next(db.session_dep())


def test_require_service_rejects_human():
    with pytest.raises(HTTPException):
        require_service(Principal("u", "u@x", ("dm",), is_service=False))


def test_require_service_allows_service():
    p = require_service(Principal("@svc", "", (), is_service=True))
    assert p.is_service


def test_get_or_create_map_is_idempotent(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    m1 = contract.get_or_create_map(db, "inst-1")
    m2 = contract.get_or_create_map(db, "inst-1")
    assert m1.id == m2.id
    assert m1.external_id == "inst-1"
    assert db.query(models.Map).filter_by(external_id="inst-1").count() == 1
    assert contract.session_for(db, m1).map_id == m1.id
