"""Hand over projects whose owner can no longer sign in.

Rows created before the OIDC migration have `users.subject = NULL`, and
`deps.current_user` resolves a principal to a User *by subject* — so those
projects are unreachable: no token can ever authenticate as their owner. And
because membership is owner-only to manage, nobody can be granted access to
them either. That's a one-way trap, so it needs an out-of-band fix.

`adopt_orphan_projects` transfers every such project to a subject that has
signed in at least once, keeps the legacy row on as a member (so the history
isn't thrown away, and access returns if that row ever gets a subject), and
repoints the campaign links that recorded the old owner.

Run it from the CLI:

    uv run python -m dungml_backend.adopt dev-user
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from . import models


class UnknownSubject(Exception):
    """No user with that subject — they have to sign in once first."""


def _orphan_user_ids(db: DbSession) -> list[str]:
    """Users who can never authenticate: no subject, or an empty one."""
    return list(
        db.scalars(
            select(models.User.id).where(
                or_(models.User.subject.is_(None), models.User.subject == "")
            )
        ).all()
    )


def adopt_orphan_projects(db: DbSession, subject: str) -> list[models.Project]:
    """Transfer every orphaned project to `subject`. Returns what moved.

    Idempotent: a second run finds no orphan-owned projects and returns [].
    """
    new_owner = db.scalar(select(models.User).where(models.User.subject == subject))
    if new_owner is None:
        raise UnknownSubject(
            f"no user with subject '{subject}' — sign in once, then re-run"
        )
    orphan_ids = _orphan_user_ids(db)
    if not orphan_ids:
        return []
    projects = list(
        db.scalars(
            select(models.Project).where(models.Project.user_id.in_(orphan_ids))
        ).all()
    )
    if not projects:
        return []
    for proj in projects:
        previous = proj.user_id
        proj.user_id = new_owner.id
        if previous != new_owner.id and db.get(
            models.ProjectMember, (proj.id, previous)
        ) is None:
            db.add(models.ProjectMember(project_id=proj.id, user_id=previous))
        for link in db.scalars(
            select(models.CampaignLink).where(
                models.CampaignLink.project_id == proj.id
            )
        ).all():
            link.user_id = new_owner.id
    db.commit()
    for proj in projects:
        db.refresh(proj)
    return projects


def main(argv: list[str] | None = None) -> int:
    import sys

    from .db import ensure_columns, get_sessionmaker, init_schema

    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m dungml_backend.adopt <subject>", file=sys.stderr)
        return 2
    init_schema()
    ensure_columns()
    db = get_sessionmaker()()
    try:
        moved = adopt_orphan_projects(db, args[0])
    except UnknownSubject as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    if not moved:
        print("nothing to adopt — no projects owned by an unreachable user")
    for proj in moved:
        print(f"adopted: {proj.name} ({proj.id})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
