from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.errors import AppError
from app.core.permissions import ROLE_PERMISSIONS
from app.db.session import get_db
from app.models import Organization, OrganizationMember, User
from app.schemas import MemberAdd, MemberOut, MemberUpdate, OrgCreate, OrgOut, OrgUpdate
from app.services.audit import log_audit

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _org_out(org: Organization, role: str) -> OrgOut:
    out = OrgOut.model_validate(org)
    out.role = role
    return out


def _membership(db: Session, org_id: str, user: User, perm: str | None = None) -> OrganizationMember:
    m = db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id == org_id, OrganizationMember.user_id == user.id))
    if not m:
        raise AppError("FORBIDDEN", "You are not a member of this organization.", 403)
    if perm and perm not in ROLE_PERMISSIONS[m.role]:
        raise AppError("FORBIDDEN", "Your role does not allow this action.", 403, {"required_permission": perm})
    return m


@router.get("", response_model=list[OrgOut])
def list_orgs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Organization, OrganizationMember.role).join(OrganizationMember).where(
        OrganizationMember.user_id == user.id).order_by(Organization.created_at)).all()
    return [_org_out(o, r) for o, r in rows]


@router.post("", response_model=OrgOut, status_code=201)
def create_org(body: OrgCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = Organization(name=body.name.strip(), default_currency=body.default_currency.upper())
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="ADMIN"))
    db.commit()
    return _org_out(org, "ADMIN")


@router.get("/{org_id}", response_model=OrgOut)
def get_org(org_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = _membership(db, org_id, user)
    return _org_out(db.get(Organization, org_id), m.role)


@router.patch("/{org_id}", response_model=OrgOut)
def update_org(org_id: str, body: OrgUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = _membership(db, org_id, user, "settings:manage")
    org = db.get(Organization, org_id)
    data = body.model_dump(exclude_unset=True)
    if "match_review_threshold" in data or "match_high_threshold" in data:
        hi = data.get("match_high_threshold", org.match_high_threshold)
        lo = data.get("match_review_threshold", org.match_review_threshold)
        if lo >= hi:
            raise AppError("INVALID_THRESHOLDS", "The review threshold must be lower than the high-confidence threshold.", 422)
    before = {k: getattr(org, k) for k in data}
    for k, v in data.items():
        setattr(org, k, v)
    log_audit(db, org.id, user.id, "organization", org.id, "organization.update", before, data)
    db.commit()
    return _org_out(org, m.role)


@router.get("/{org_id}/members", response_model=list[MemberOut])
def list_members(org_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _membership(db, org_id, user)
    rows = db.scalars(select(OrganizationMember).where(OrganizationMember.organization_id == org_id).order_by(OrganizationMember.created_at)).all()
    return [MemberOut(id=m.id, user_id=m.user_id, email=m.user.email, display_name=m.user.display_name, role=m.role) for m in rows]


@router.post("/{org_id}/members", response_model=MemberOut, status_code=201)
def add_member(org_id: str, body: MemberAdd, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _membership(db, org_id, user, "members:manage")
    target = db.scalar(select(User).where(User.email == body.email.lower()))
    if not target:
        raise AppError("USER_NOT_FOUND", "No registered user has this email. Ask them to register first.", 404)
    if db.scalar(select(OrganizationMember.id).where(OrganizationMember.organization_id == org_id, OrganizationMember.user_id == target.id)):
        raise AppError("ALREADY_MEMBER", "This user is already a member.", 409)
    m = OrganizationMember(organization_id=org_id, user_id=target.id, role=body.role)
    db.add(m)
    db.flush()
    log_audit(db, org_id, user.id, "member", m.id, "member.add", None, {"email": target.email, "role": body.role})
    db.commit()
    return MemberOut(id=m.id, user_id=target.id, email=target.email, display_name=target.display_name, role=m.role)


def _last_admin(db: Session, org_id: str, member: OrganizationMember) -> bool:
    n = db.scalar(select(func.count(OrganizationMember.id)).where(OrganizationMember.organization_id == org_id, OrganizationMember.role == "ADMIN"))
    return member.role == "ADMIN" and n <= 1


@router.patch("/{org_id}/members/{member_id}", response_model=MemberOut)
def update_member(org_id: str, member_id: str, body: MemberUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _membership(db, org_id, user, "members:manage")
    m = db.scalar(select(OrganizationMember).where(OrganizationMember.id == member_id, OrganizationMember.organization_id == org_id))
    if not m:
        raise AppError("MEMBER_NOT_FOUND", "Member not found.", 404)
    if body.role != "ADMIN" and _last_admin(db, org_id, m):
        raise AppError("LAST_ADMIN", "An organization must keep at least one admin.", 409)
    before = m.role
    m.role = body.role
    log_audit(db, org_id, user.id, "member", m.id, "member.role_change", {"role": before}, {"role": body.role})
    db.commit()
    return MemberOut(id=m.id, user_id=m.user_id, email=m.user.email, display_name=m.user.display_name, role=m.role)


@router.delete("/{org_id}/members/{member_id}", status_code=204)
def remove_member(org_id: str, member_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _membership(db, org_id, user, "members:manage")
    m = db.scalar(select(OrganizationMember).where(OrganizationMember.id == member_id, OrganizationMember.organization_id == org_id))
    if not m:
        raise AppError("MEMBER_NOT_FOUND", "Member not found.", 404)
    if _last_admin(db, org_id, m):
        raise AppError("LAST_ADMIN", "An organization must keep at least one admin.", 409)
    log_audit(db, org_id, user.id, "member", m.id, "member.remove", {"user_id": m.user_id, "role": m.role}, None)
    db.delete(m)
    db.commit()
