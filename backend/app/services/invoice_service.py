from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, Invoice, InvoiceLineItem, ReconciliationAllocation
from app.processors.normalize import normalize_vendor
from app.processors.validators import validate_invoice
from app.services import duplicate_service
from app.services.audit import jsonable, log_audit

EDITABLE = ("vendor_name", "invoice_number", "invoice_date", "due_date", "currency", "subtotal", "tax_amount",
            "discount_amount", "total_amount", "tax_id", "description", "category", "payment_status")


def snapshot(inv: Invoice) -> dict:
    d = {f: jsonable(getattr(inv, f)) for f in EDITABLE}
    d["line_items"] = [{k: jsonable(getattr(li, k)) for k in ("description", "quantity", "unit_price", "tax_amount", "line_total")}
                       for li in inv.line_items]
    return d


def revalidate(inv: Invoice) -> None:
    data = {f: getattr(inv, f) for f in EDITABLE}
    items = [{k: getattr(li, k) for k in ("quantity", "unit_price", "tax_amount", "line_total")} for li in inv.line_items]
    inv.warnings = validate_invoice(data, items, inv.uncertain_fields or [])


def has_allocations(db: Session, invoice_id: str) -> bool:
    return db.scalar(select(ReconciliationAllocation.id).where(ReconciliationAllocation.invoice_id == invoice_id).limit(1)) is not None


def set_line_items(inv: Invoice, items: list[dict]) -> None:
    inv.line_items.clear()
    for n, it in enumerate(items):
        inv.line_items.append(InvoiceLineItem(
            position=n, description=it.get("description"), quantity=it.get("quantity"), unit_price=it.get("unit_price"),
            tax_amount=it.get("tax_amount"), line_total=it.get("line_total")))


def review_reasons(inv: Invoice, db: Session | None = None) -> list[str]:
    reasons = []
    ws = inv.warnings or []
    codes = {w["code"] for w in ws}
    if "MISSING_INVOICE_NUMBER" in codes:
        reasons.append("Missing invoice number")
    if "UNCERTAIN_INVOICE_DATE" in codes or "MISSING_INVOICE_DATE" in codes:
        reasons.append("Uncertain invoice date")
    if "UNCERTAIN_CURRENCY" in codes or "MISSING_CURRENCY" in codes:
        reasons.append("Ambiguous currency")
    if "TOTAL_MISMATCH" in codes or "LINE_ITEMS_SUM_MISMATCH" in codes:
        reasons.append("Total mismatch")
    if any(v < 0.6 for v in (inv.field_confidence or {}).values()) or "MISSING_TOTAL_AMOUNT" in codes or "MISSING_VENDOR_NAME" in codes:
        reasons.append("Low-confidence extraction")
    if db is not None and duplicate_service.open_flags(db, inv.document_id):
        reasons.append("Potential duplicate")
    if inv.reconciliation_status == "NEEDS_REVIEW":
        reasons.append("Reconciliation conflict")
    return list(dict.fromkeys(reasons))


def after_edit_status(db: Session, inv: Invoice) -> None:
    """Re-run duplicate detection and set document status consistently after any change."""
    duplicate_service.detect_invoice_duplicates(db, inv)
    db.flush()
    set_document_status(db, inv)


def set_document_status(db: Session, inv: Invoice) -> None:
    doc: Document = inv.document
    if doc.processing_status in ("ARCHIVED", "FAILED"):
        return
    if inv.reconciliation_status == "CONFIRMED" and inv.review_status == "VERIFIED":
        doc.processing_status = "RECONCILED"
    elif inv.review_status == "VERIFIED":
        doc.processing_status = "READY_FOR_RECONCILIATION"
    elif duplicate_service.open_flags(db, doc.id):
        doc.processing_status = "DUPLICATE_REVIEW"
    else:
        doc.processing_status = "REVIEW_REQUIRED"


def verify(db: Session, inv: Invoice, user_id: str) -> None:
    inv.review_status = "VERIFIED"
    inv.verified_by, inv.verified_at = user_id, datetime.now(timezone.utc)
    inv.uncertain_fields = []
    set_document_status(db, inv)
    log_audit(db, inv.organization_id, user_id, "invoice", inv.id, "invoice.verify", None, {"review_status": "VERIFIED"})
