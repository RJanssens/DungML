# packages/backend/tests/test_identity.py
"""The dungml auth seam (Plan 1): static dev mode + Keycloak JWT mode."""
import pytest

from dungml_backend.identity import (
    IdentityError,
    Principal,
    StaticIdentityProvider,
    get_identity_provider,
)


def test_static_provider_maps_dev_tokens():
    p = StaticIdentityProvider({"dev-user": Principal("u1", "u1@dev", ("dm",), False),
                                "dev-service": Principal("@svc", "svc@dev", (), True)})
    assert p.authenticate("dev-user").subject == "u1"
    svc = p.authenticate("dev-service")
    assert svc.is_service is True


def test_static_provider_rejects_unknown():
    with pytest.raises(IdentityError):
        StaticIdentityProvider({}).authenticate("nope")


def test_get_identity_provider_static_by_default(monkeypatch):
    monkeypatch.setenv("DUNGML_AUTH_MODE", "static")
    from dungml_backend import config
    config.reload_settings()
    assert isinstance(get_identity_provider(), StaticIdentityProvider)
