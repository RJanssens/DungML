"""Adopting projects whose owner can no longer sign in.

Rows created before OIDC have `users.subject = NULL`, and `current_user`
resolves by subject — so nobody can reach those projects, and with member
management being owner-only, nobody can be given access to them either.
`adopt.adopt_orphan_projects` hands them to a subject that *can* sign in.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def db(client):
    """A DB session on the test database (the client fixture binds it)."""
    from dungml_backend.db import get_sessionmaker

    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()


def _legacy_project(db, name: str = "Stonehell Dungeon"):
    from dungml_backend import models

    legacy = models.User(subject=None, email="old@example.com")
    db.add(legacy)
    db.flush()
    proj = models.Project(user_id=legacy.id, name=name)
    db.add(proj)
    db.commit()
    return legacy, proj


def _signed_in_user(db, subject: str = "dev-user"):
    from dungml_backend import models

    u = models.User(subject=subject, email=f"{subject}@dungml.local")
    db.add(u)
    db.commit()
    return u


def test_adopts_a_project_whose_owner_has_no_subject(db):
    from dungml_backend import adopt

    legacy, proj = _legacy_project(db)
    me = _signed_in_user(db)

    adopted = adopt.adopt_orphan_projects(db, "dev-user")

    assert [p.id for p in adopted] == [proj.id]
    db.refresh(proj)
    assert proj.user_id == me.id


def test_keeps_the_legacy_owner_as_a_member(db):
    from dungml_backend import adopt, models

    legacy, proj = _legacy_project(db)
    _signed_in_user(db)

    adopt.adopt_orphan_projects(db, "dev-user")

    assert db.get(models.ProjectMember, (proj.id, legacy.id)) is not None


def test_repoints_campaign_links_at_the_new_owner(db):
    from dungml_backend import adopt, models

    legacy, proj = _legacy_project(db)
    me = _signed_in_user(db)
    db.add(
        models.CampaignLink(
            external_id="return-to-stonehell", project_id=proj.id, user_id=legacy.id
        )
    )
    db.commit()

    adopt.adopt_orphan_projects(db, "dev-user")

    link = db.get(models.CampaignLink, "return-to-stonehell")
    assert link.user_id == me.id


def test_is_idempotent(db):
    from dungml_backend import adopt

    _legacy_project(db)
    _signed_in_user(db)

    first = adopt.adopt_orphan_projects(db, "dev-user")
    second = adopt.adopt_orphan_projects(db, "dev-user")

    assert len(first) == 1
    assert second == []


def test_leaves_projects_with_a_reachable_owner_alone(db):
    from dungml_backend import adopt, models

    other = models.User(subject="someone-else", email="them@example.com")
    db.add(other)
    db.flush()
    theirs = models.Project(user_id=other.id, name="Theirs")
    db.add(theirs)
    db.commit()
    _signed_in_user(db)

    assert adopt.adopt_orphan_projects(db, "dev-user") == []
    db.refresh(theirs)
    assert theirs.user_id == other.id


def test_refuses_a_subject_that_has_never_signed_in(db):
    from dungml_backend import adopt

    _legacy_project(db)
    with pytest.raises(adopt.UnknownSubject):
        adopt.adopt_orphan_projects(db, "nobody")


def test_treats_an_empty_subject_as_orphaned(db):
    from dungml_backend import adopt, models

    legacy = models.User(subject="", email="blank@example.com")
    db.add(legacy)
    db.flush()
    proj = models.Project(user_id=legacy.id, name="Blank")
    db.add(proj)
    db.commit()
    _signed_in_user(db)

    assert [p.id for p in adopt.adopt_orphan_projects(db, "dev-user")] == [proj.id]
