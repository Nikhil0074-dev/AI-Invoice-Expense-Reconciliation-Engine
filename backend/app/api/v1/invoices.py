from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Ctx, require
from app.core.errors import AppError
from app.models import Document, Invoice, ReconciliationMatch
from app.processors.normalize import currency_decimals, normalize_vendor
from app.processors.validators import blocking_errors
from app.schemas import InvoiceOut, InvoiceUpdate, LineItemOut, VerifyIn
from app.services import duplicate_service, invoice_service
from app.services.audit import jsonable, log_audit
from app.services.reconciliation_service import invoice_allocated

router = APIRouter(prefix="/invoices", tags=["invoices"])
SOFT_FIELDS = {"category", "description", "payment_status", "tax_id", "due_date"}


def _out(db: Session, inv: Invoice) -> InvoiceOut:
    out = InvoiceOut.model_validate(inv)
    out.review_reasons = invoice_service.review_reasons(inv, db)
    out.document_status = inv.document.processing_status
    out.original_filename, out.mime_type = inv.document.original_filename, inv.document.mime_type
    out.allocated_amount = invoice_allocated(db, inv.id)
    return out


def get_invoice(ctx: Ctx, invoice_id: str) -> Invoice:
    inv = ctx.db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == ctx.org.id))
    if not inv:
        raise AppError("INVOICE_NOT_FOUND", "Invoice not found.", 404)
    return inv


@router.get("")
def list_invoices(q: str | None = None, review_status: str | None = None, reconciliation_status: str | None = None,
                  currency: str | None = None, category: str | None = None, date_from: date | None = None, date_to: date | None = None,
                  needs_review: bool = False, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                  ctx: Ctx = Depends(require("invoices:read"))):
    db = ctx.db
    stmt = select(Invoice).join(Document, Invoice.document_id == Document.id).where(
        Invoice.organization_id == ctx.org.id, Document.processing_status != "ARCHIVED")
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Invoice.vendor_name.ilike(like), Invoice.invoice_number.ilike(like)))
    if needs_review:
        stmt = stmt.where(Invoice.review_status != "VERIFIED")
    if review_status:
        stmt = stmt.where(Invoice.review_status == review_status)
    if reconciliation_status:
        stmt = stmt.where(Invoice.reconciliation_status == reconciliation_status)
    if currency:
        stmt = stmt.where(Invoice.currency == currency.upper())
    if category:
        stmt = stmt.where(Invoice.category == category)
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Invoice.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_out(db, i) for i in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/{invoice_id}", response_model=InvoiceOut)
def read_invoice(invoice_id: str, ctx: Ctx = Depends(require("invoices:read"))):
    return _out(ctx.db, get_invoice(ctx, invoice_id))


@router.get("/{invoice_id}/line-items", response_model=list[LineItemOut])
def read_line_items(invoice_id: str, ctx: Ctx = Depends(require("invoices:read"))):
    return get_invoice(ctx, invoice_id).line_items


@router.patch("/{invoice_id}", response_model=InvoiceOut)
def correct_invoice(invoice_id: str, body: InvoiceUpdate, ctx: Ctx = Depends(require("invoices:edit"))):
    db, inv = ctx.db, get_invoice(ctx, invoice_id)
    data = body.model_dump(exclude_unset=True)
    items = data.pop("line_items", None)
    cur = data.get("currency", inv.currency)
    for f in ("subtotal", "tax_amount", "discount_amount", "total_amount"):
        v = data.get(f)
        if v is not None and cur and -v.normalize().as_tuple().exponent > currency_decimals(cur):
            raise AppError("INVALID_AMOUNT", f"{f} has more decimal places than {cur} allows.", 422, {"field": f})
    reconciled = invoice_service.has_allocations(db, inv.id)
    changed = {f: v for f, v in data.items() if f in invoice_service.EDITABLE and getattr(inv, f) != v}
    if reconciled and (set(changed) - SOFT_FIELDS or items is not None):
        raise AppError("INVOICE_RECONCILED", "Financial fields cannot be changed while the invoice is reconciled. Unlink it first.", 409)
    before = invoice_service.snapshot(inv)
    for f, v in changed.items():
        setattr(inv, f, v)
    if items is not None:
        invoice_service.set_line_items(inv, items)
    if "vendor_name" in changed:
        inv.normalized_vendor_name = normalize_vendor(inv.vendor_name)
    conf = dict(inv.field_confidence or {})
    for f in changed:
        conf[f] = 1.0
    inv.field_confidence = conf
    inv.uncertain_fields = [u for u in (inv.uncertain_fields or []) if u not in changed]
    if inv.review_status == "VERIFIED" and (set(changed) - {"category", "description", "payment_status"} or items is not None):
        inv.review_status = "REVIEW_REQUIRED"
        for m in db.scalars(select(ReconciliationMatch).where(ReconciliationMatch.invoice_id == inv.id,
                                                              ReconciliationMatch.match_status.in_(["SUGGESTED", "NEEDS_REVIEW"]))):
            db.delete(m)
        inv.reconciliation_status = "UNMATCHED"
    db.flush()
    invoice_service.revalidate(inv)
    invoice_service.after_edit_status(db, inv)
    after = invoice_service.snapshot(inv)
    diff_b = {k: before[k] for k in after if before[k] != after[k]}
    diff_a = {k: after[k] for k in diff_b}
    if diff_b:
        log_audit(db, ctx.org.id, ctx.user.id, "invoice", inv.id, "invoice.correct", diff_b, diff_a)
    db.commit()
    return _out(db, inv)


@router.post("/{invoice_id}/verify", response_model=InvoiceOut)
def verify_invoice(invoice_id: str, body: VerifyIn, ctx: Ctx = Depends(require("invoices:verify"))):
    db, inv = ctx.db, get_invoice(ctx, invoice_id)
    errors = blocking_errors(inv.warnings or [])
    if errors:
        raise AppError("VERIFICATION_BLOCKED", "Required fields are missing: " + "; ".join(e["message"] for e in errors), 422,
                       {"errors": errors})
    dup = duplicate_service.blocking_flags(db, inv.document_id)
    if dup:
        raise AppError("DUPLICATE_REVIEW_PENDING", "Review the duplicate warning(s) for this document before verifying it.", 409,
                       {"flags": [f.id for f in dup]})
    pending = [w for w in (inv.warnings or []) if w["severity"] == "warning"]
    if pending and not body.acknowledge_warnings:
        raise AppError("WARNINGS_NOT_ACKNOWLEDGED", "This invoice has validation warnings. Acknowledge them to verify.", 409,
                       {"warnings": pending})
    invoice_service.verify(db, inv, ctx.user.id)
    invoice_service.revalidate(inv)
    db.commit()
    return _out(db, inv)
