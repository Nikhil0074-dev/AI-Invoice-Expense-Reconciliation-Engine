from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import Ctx, require
from app.core.errors import AppError
from app.models import Document, DuplicateFlag
from app.schemas import DuplicateOut, DuplicateReview
from app.services import invoice_service
from app.services.audit import log_audit

router = APIRouter(prefix="/duplicates", tags=["duplicates"])


def _out(ctx: Ctx, f: DuplicateFlag) -> DuplicateOut:
    out = DuplicateOut.model_validate(f)
    a, b = ctx.db.get(Document, f.document_id), ctx.db.get(Document, f.possible_duplicate_document_id)
    out.document_filename, out.possible_duplicate_filename = a.original_filename, b.original_filename
    return out


@router.get("", response_model=list[DuplicateOut])
def list_duplicates(status: str | None = "OPEN", ctx: Ctx = Depends(require("duplicates:read"))):
    stmt = select(DuplicateFlag).where(DuplicateFlag.organization_id == ctx.org.id)
    if status:
        stmt = stmt.where(DuplicateFlag.review_status == status.upper())
    return [_out(ctx, f) for f in ctx.db.scalars(stmt.order_by(DuplicateFlag.created_at.desc())).all()]


@router.post("/{flag_id}/review", response_model=DuplicateOut)
def review(flag_id: str, body: DuplicateReview, ctx: Ctx = Depends(require("duplicates:review"))):
    db = ctx.db
    f = db.scalar(select(DuplicateFlag).where(DuplicateFlag.id == flag_id, DuplicateFlag.organization_id == ctx.org.id))
    if not f:
        raise AppError("DUPLICATE_NOT_FOUND", "Duplicate flag not found.", 404)
    if f.review_status != "OPEN":
        raise AppError("ALREADY_REVIEWED", "This flag has already been reviewed.", 409)
    doc = db.get(Document, f.document_id)
    if body.decision == "confirm_duplicate":
        if doc.invoice and invoice_service.has_allocations(db, doc.invoice.id):
            raise AppError("INVOICE_RECONCILED", "This invoice is reconciled; unlink it before archiving it as a duplicate.", 409)
        f.review_status = "CONFIRMED_DUPLICATE"
        doc.processing_status = "ARCHIVED"  # never deleted automatically; excluded from totals and exports
    else:
        f.review_status = "DISMISSED"
    f.review_note, f.reviewed_by, f.reviewed_at = body.note, ctx.user.id, datetime.now(timezone.utc)
    # one decision covers every open flag for the same pair (or, when archiving, for the whole document)
    cond = [DuplicateFlag.document_id == doc.id, DuplicateFlag.review_status == "OPEN", DuplicateFlag.id != f.id]
    if body.decision == "dismiss":
        cond.append(DuplicateFlag.possible_duplicate_document_id == f.possible_duplicate_document_id)
    for other in db.scalars(select(DuplicateFlag).where(*cond)):
        other.review_status, other.review_note = f.review_status, body.note
        other.reviewed_by, other.reviewed_at = ctx.user.id, f.reviewed_at
    db.flush()
    if body.decision == "dismiss" and doc.invoice:
        invoice_service.set_document_status(db, doc.invoice)
    log_audit(db, ctx.org.id, ctx.user.id, "duplicate_flag", f.id, f"duplicate.{body.decision}", {"review_status": "OPEN"},
              {"review_status": f.review_status, "document_id": doc.id})
    db.commit()
    return _out(ctx, f)
