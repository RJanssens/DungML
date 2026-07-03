# packages/backend/tests/test_identity.py
"""The dungml auth seam (Plan 1): static dev mode + Keycloak JWT mode."""
import pytest

from dungml_backend.identity import (
    IdentityError,
    Principal,
    StaticIdentityProvider,
    display_name,
    get_identity_provider,
    principal_from_claims,
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


def test_principal_from_claims_extracts_profile_fields():
    claims = {
        "sub": "kc-123",
        "email": "raf@example.org",
        "preferred_username": "raf",
        "name": "Raf Janssens",
        "realm_access": {"roles": ["dm"]},
        "azp": "dungml-web",
    }
    p = principal_from_claims(claims, service_client_id="dungeon-daemon-service")
    assert p.subject == "kc-123"
    assert p.username == "raf"
    assert p.name == "Raf Janssens"
    assert p.email == "raf@example.org"
    assert p.roles == ("dm",)
    assert p.is_service is False


def test_principal_from_claims_flags_service_by_azp():
    p = principal_from_claims(
        {"sub": "svc", "azp": "dungeon-daemon-service"},
        service_client_id="dungeon-daemon-service",
    )
    assert p.is_service is True


def test_principal_from_claims_requires_subject():
    with pytest.raises(IdentityError):
        principal_from_claims({"preferred_username": "x"}, service_client_id="svc")


def test_display_name_fallback_chain():
    assert display_name(Principal("s", "e@x", (), False, "uname", "Full Name")) == "Full Name"
    assert display_name(Principal("s", "e@x", (), False, "uname", "")) == "uname"
    assert display_name(Principal("s", "e@x", (), False, "", "")) == "e@x"
    assert display_name(Principal("s", "", (), False, "", "")) == "s"
