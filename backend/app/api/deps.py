from dataclasses import dataclass

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.permissions import ROLE_PERMISSIONS
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Organization, OrganizationMember, User

bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not creds:
        raise AppError("UNAUTHENTICATED", "Authentication required.", 401)
    user = db.get(User, decode_token(creds.credentials))
    if not user:
        raise AppError("UNAUTHENTICATED", "User no longer exists.", 401)
    return user


@dataclass
class Ctx:
    user: User
    org: Organization
    role: str
    db: Session


def get_ctx(x_organization_id: str | None = Header(default=None), user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> Ctx:
    members = db.scalars(select(OrganizationMember).where(OrganizationMember.user_id == user.id)).all()
    if x_organization_id is None:
        if len(members) == 1:
            m = members[0]
        else:
            raise AppError("ORGANIZATION_REQUIRED", "Send the X-Organization-Id header.", 400)
    else:
        m = next((x for x in members if x.organization_id == x_organization_id), None)
        if not m:  # same response whether the org exists or not: no information leak
            raise AppError("FORBIDDEN", "You are not a member of this organization.", 403)
    org = db.get(Organization, m.organization_id)
    return Ctx(user=user, org=org, role=m.role, db=db)


def require(perm: str):
    def dep(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        if perm not in ROLE_PERMISSIONS.get(ctx.role, set()):
            raise AppError("FORBIDDEN", "Your role does not allow this action.", 403, {"required_permission": perm})
        return ctx
    return dep
