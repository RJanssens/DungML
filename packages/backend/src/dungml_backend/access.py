"""Who may touch a project — its owner or one of its members.

A project has exactly one owner (`projects.user_id`) plus any number of
`ProjectMember` rows. Every route that reads or edits a project, its maps,
its DSL or its play sessions authorizes through here, so the rule lives in
one place rather than in the copies of `proj.user_id != user.id` this
replaces.

Two failure modes, deliberately different:

- **No access at all → 404.** Same as before: don't leak that a project or
  map exists to someone who can't see it.
- **Access, but the action is owner-only → 403.** A member can already see
  the project, so hiding its existence would be theatre. Deleting a project
  and managing its membership are the owner-only actions.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from . import models


def is_member(db: DbSession, project_id: str, user: models.User) -> bool:
    return db.get(models.ProjectMember, (project_id, user.id)) is not None


def can_access(db: DbSession, project: models.Project, user: models.User) -> bool:
    return project.user_id == user.id or is_member(db, project.id, user)


def accessible_project(
    db: DbSession, project_id: str, user: models.User
) -> models.Project | None:
    proj = db.get(models.Project, project_id)
    if proj is None or not can_access(db, proj, user):
        return None
    return proj


def get_project(db: DbSession, project_id: str, user: models.User) -> models.Project:
    """The project, if this user owns it or is a member. 404 otherwise."""
    proj = accessible_project(db, project_id, user)
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return proj


def get_map(db: DbSession, map_id: str, user: models.User) -> models.Map:
    """The map, if this user can access its project. 404 otherwise."""
    m = db.get(models.Map, map_id)
    if m is None or not can_access(db, m.project, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "map not found")
    return m


def require_owner(project: models.Project, user: models.User) -> models.Project:
    """Gate an owner-only action. 403 — the caller can see the project."""
    if project.user_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "only the project owner can do that"
        )
    return project


def list_projects(db: DbSession, user: models.User) -> list[models.Project]:
    """Every project this user owns or is a member of, most recent first."""
    member_ids = select(models.ProjectMember.project_id).where(
        models.ProjectMember.user_id == user.id
    )
    rows = db.scalars(
        select(models.Project)
        .where(
            or_(
                models.Project.user_id == user.id,
                models.Project.id.in_(member_ids),
            )
        )
        .order_by(models.Project.updated_at.desc())
    ).all()
    return list(rows)


def find_user(db: DbSession, identifier: str) -> models.User | None:
    """Resolve a user by subject or email — how a project owner names someone
    to share with. No JIT creation: a typo must not conjure an account, so the
    person has to have signed in at least once."""
    ident = (identifier or "").strip()
    if not ident:
        return None
    return db.scalar(
        select(models.User).where(
            or_(models.User.subject == ident, models.User.email == ident)
        )
    )
