from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import Ctx, require
from app.api.v1.invoices import get_invoice
from app.api.v1.transactions import tx_out
from app.core.errors import AppError
from app.models import BankTransaction, Invoice, ReconciliationMatch
from app.schemas import MatchCreate, MatchOut, MatchPatch
from app.services import reconciliation_service as rs

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


def _match_out(ctx: Ctx, m: ReconciliationMatch) -> MatchOut:
    out = MatchOut.model_validate(m)
    ids = m.transaction_ids or []
    if ids:
        alloc = rs.tx_allocated_map(ctx.db, ctx.org.id, ids)
        txs = ctx.db.scalars(select(BankTransaction).where(BankTransaction.id.in_(ids), BankTransaction.organization_id == ctx.org.id)).all()
        out.transactions = [tx_out(t, alloc.get(t.id, Decimal(0))) for t in txs]
    return out


def _get_match(ctx: Ctx, match_id: str) -> ReconciliationMatch:
    m = ctx.db.scalar(select(ReconciliationMatch).where(ReconciliationMatch.id == match_id, ReconciliationMatch.organization_id == ctx.org.id))
    if not m:
        raise AppError("MATCH_NOT_FOUND", "Match not found.", 404)
    return m


@router.get("/suggestions", response_model=list[MatchOut])
def suggestions(invoice_id: str | None = None, refresh: bool = Query(True), ctx: Ctx = Depends(require("reconciliation:read"))):
    """With invoice_id: (re)compute suggestions for that invoice. Without: list stored open suggestions."""
    db = ctx.db
    if invoice_id:
        inv = get_invoice(ctx, invoice_id)
        if refresh:
            from app.core.permissions import ROLE_PERMISSIONS
            if "reconciliation:write" not in ROLE_PERMISSIONS[ctx.role]:
                raise AppError("FORBIDDEN", "Your role cannot generate suggestions; ask an accountant.", 403)
            rs.generate_suggestions(db, ctx.org, inv)
            db.commit()
        rows = db.scalars(select(ReconciliationMatch).where(
            ReconciliationMatch.invoice_id == inv.id, ReconciliationMatch.match_status.in_(["SUGGESTED", "NEEDS_REVIEW"]))
            .order_by(ReconciliationMatch.match_score.desc())).all()
    else:
        rows = db.scalars(select(ReconciliationMatch).where(
            ReconciliationMatch.organization_id == ctx.org.id, ReconciliationMatch.match_status.in_(["SUGGESTED", "NEEDS_REVIEW"]))
            .order_by(ReconciliationMatch.match_score.desc())).all()
    return [_match_out(ctx, m) for m in rows]


@router.post("/run")
def run_all(ctx: Ctx = Depends(require("reconciliation:write"))):
    """Generate suggestions for every verified, not fully reconciled invoice."""
    db, count = ctx.db, 0
    for inv in db.scalars(select(Invoice).where(Invoice.organization_id == ctx.org.id, Invoice.review_status == "VERIFIED",
                                                Invoice.reconciliation_status != "CONFIRMED")):
        count += len(rs.generate_suggestions(db, ctx.org, inv))
    db.commit()
    return {"suggestions_created": count}


@router.get("/matches", response_model=list[MatchOut])
def list_matches(invoice_id: str | None = None, status: str | None = None, ctx: Ctx = Depends(require("reconciliation:read"))):
    stmt = select(ReconciliationMatch).where(ReconciliationMatch.organization_id == ctx.org.id)
    if invoice_id:
        stmt = stmt.where(ReconciliationMatch.invoice_id == invoice_id)
    if status:
        stmt = stmt.where(ReconciliationMatch.match_status == status)
    return [_match_out(ctx, m) for m in ctx.db.scalars(stmt.order_by(ReconciliationMatch.created_at.desc())).all()]


@router.post("/matches", response_model=MatchOut, status_code=201)
def create_or_confirm(body: MatchCreate, ctx: Ctx = Depends(require("reconciliation:write"))):
    db = ctx.db
    if body.match_id:
        m = rs.confirm_match(db, ctx.org, _get_match(ctx, body.match_id), ctx.user.id)
    elif body.invoice_id and body.allocations:
        m = rs.manual_match(db, ctx.org, body.invoice_id, [{"transaction_id": a.transaction_id, "amount": a.amount} for a in body.allocations], ctx.user.id)
    else:
        raise AppError("INVALID_REQUEST", "Provide match_id to confirm a suggestion, or invoice_id with allocations for a manual match.", 422)
    db.commit()
    return _match_out(ctx, m)


@router.patch("/matches/{match_id}", response_model=MatchOut)
def update_match(match_id: str, body: MatchPatch, ctx: Ctx = Depends(require("reconciliation:write"))):
    m = _get_match(ctx, match_id)
    m = rs.confirm_match(ctx.db, ctx.org, m, ctx.user.id) if body.action == "confirm" else rs.unlink_match(ctx.db, ctx.org, m, ctx.user.id)
    ctx.db.commit()
    return _match_out(ctx, m)


@router.post("/matches/{match_id}/reject", response_model=MatchOut)
def reject(match_id: str, ctx: Ctx = Depends(require("reconciliation:write"))):
    m = rs.reject_match(ctx.db, ctx.org, _get_match(ctx, match_id), ctx.user.id)
    ctx.db.commit()
    return _match_out(ctx, m)
