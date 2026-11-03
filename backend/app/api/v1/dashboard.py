from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import Ctx, require
from app.models import AuditLog, User
from app.schemas import AuditOut
from app.services.dashboard_service import build_dashboard

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(date_from: date | None = None, date_to: date | None = None, ctx: Ctx = Depends(require("dashboard:read"))):
    return build_dashboard(ctx.db, ctx.org, date_from, date_to)


@router.get("/audit-logs", response_model=list[AuditOut])
def audit_logs(entity_type: str | None = None, entity_id: str | None = None, limit: int = Query(100, ge=1, le=500),
               ctx: Ctx = Depends(require("audit:read"))):
    stmt = select(AuditLog).where(AuditLog.organization_id == ctx.org.id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    rows = ctx.db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit)).all()
    names = {u.id: u.display_name for u in ctx.db.scalars(select(User).where(User.id.in_({r.actor_user_id for r in rows if r.actor_user_id})))}
    out = []
    for r in rows:
        o = AuditOut.model_validate(r)
        o.actor_name = names.get(r.actor_user_id) if r.actor_user_id else "System"
        out.append(o)
    return out
