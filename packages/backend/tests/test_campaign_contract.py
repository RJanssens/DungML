"""Campaign-link contract helpers (sub-project B)."""
from dungml_backend import contract, models
from dungml_backend.db import get_sessionmaker


def _db():
    return get_sessionmaker()()


def _user_project_map(db, subject="gm-1"):
    u = models.User(subject=subject, email=f"{subject}@t.local")
    db.add(u); db.flush()
    p = models.Project(user_id=u.id, name="Keep")
    db.add(p); db.flush()
    m = models.Map(project_id=p.id, name="L1", source='map "M" {}')
    db.add(m); db.commit(); db.refresh(u); db.refresh(p); db.refresh(m)
    return u, p, m


def test_link_and_lookup(client):  # client fixture builds the schema + DB
    db = _db()
    u, p, m = _user_project_map(db)
    link = contract.link_campaign(db, "inst-42", p)
    assert link.external_id == "inst-42"
    assert link.project_id == p.id and link.user_id == u.id
    assert contract.linked_project(db, "inst-42").id == p.id
    assert contract.linked_project(db, "inst-nope") is None


def test_link_upsert_reassigns_project(client):
    db = _db()
    u, p1, _ = _user_project_map(db)
    p2 = models.Project(user_id=u.id, name="Other")
    db.add(p2); db.commit(); db.refresh(p2)
    contract.link_campaign(db, "inst-1", p1)
    contract.link_campaign(db, "inst-1", p2)  # re-link
    assert contract.linked_project(db, "inst-1").id == p2.id


def test_map_in_link_guards_project_membership(client):
    db = _db()
    u, p, m = _user_project_map(db)
    other = models.Map(project_id=p.id, name="x", source="")
    stray_p = models.Project(user_id=u.id, name="stray")
    db.add(stray_p); db.flush()
    stray = models.Map(project_id=stray_p.id, name="s", source="")
    db.add_all([other, stray]); db.commit(); db.refresh(m); db.refresh(stray)
    contract.link_campaign(db, "inst-7", p)
    assert contract.map_in_link(db, "inst-7", m.id).id == m.id
    assert contract.map_in_link(db, "inst-7", stray.id) is None       # not in linked project
    assert contract.map_in_link(db, "inst-unlinked", m.id) is None    # no link


def test_campaign_session_isolated_per_external_id(client):
    db = _db()
    _, p, m = _user_project_map(db)
    s1 = contract.campaign_session_for(db, m, "inst-a")
    s1b = contract.campaign_session_for(db, m, "inst-a")   # idempotent
    s2 = contract.campaign_session_for(db, m, "inst-b")
    assert s1.id == s1b.id
    assert s1.id != s2.id                                  # distinct fog per campaign
    assert s1.external_id == "inst-a" and s2.external_id == "inst-b"
