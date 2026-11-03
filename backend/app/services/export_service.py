"""CSV exports with formula-injection protection, configurable columns and export audit records."""
import csv
import hashlib
import io
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.integrations.storage import get_storage
from app.models import (BankTransaction, Document, DuplicateFlag, ExportRecord, Invoice, InvoiceLineItem,
                        ReconciliationAllocation)
from app.services.audit import log_audit
from app.services.reconciliation_service import tx_allocated_map, tx_remaining

FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(v):
    """Neutralise spreadsheet formulas in untrusted *text*. Numbers/dates are never touched."""
    if isinstance(v, str) and v and (v[0] in FORMULA_CHARS or v.lstrip()[:1] in FORMULA_CHARS):
        return "'" + v
    return v


def fmt_value(v):
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, date):
        return v.isoformat()
    return sanitize_cell(str(v)) if not isinstance(v, (int, float)) else str(v)


EXPORTS: dict[str, dict] = {
    "expense": {
        "columns": ["vendor_name", "invoice_number", "invoice_date", "currency", "subtotal", "tax_amount", "discount_amount",
                    "total_amount", "category", "reconciliation_status"],
        "required": ["vendor_name", "invoice_date", "currency", "total_amount"],
    },
    "invoice_register": {
        "columns": ["vendor_name", "invoice_number", "invoice_date", "due_date", "currency", "subtotal", "tax_amount", "discount_amount",
                    "total_amount", "tax_id", "category", "reconciliation_status", "original_filename"],
        "required": ["vendor_name", "invoice_date", "currency", "total_amount"],
    },
    "bank_reconciliation": {
        "columns": ["invoice_number", "vendor_name", "invoice_total", "currency", "transaction_date", "transaction_description",
                    "transaction_reference", "allocated_amount", "reconciliation_status"],
        "required": ["currency", "allocated_amount"],
    },
    "line_items": {
        "columns": ["invoice_number", "vendor_name", "invoice_date", "currency", "description", "quantity", "unit_price",
                    "tax_amount", "line_total"],
        "required": ["currency"],
    },
    "duplicate_review": {
        "columns": ["document", "possible_duplicate_of", "category", "method", "confidence", "review_status", "evidence"],
        "required": [],
    },
    "unmatched_transactions": {
        "columns": ["transaction_date", "description", "reference", "currency", "amount", "unallocated_amount"],
        "required": ["transaction_date", "currency", "amount"],
    },
}
TEMPLATES = {  # example header presets; real accounting systems need their own validated templates
    "generic": {},
    "simple_ledger": {"vendor_name": "Supplier", "invoice_number": "Reference", "invoice_date": "Date",
                      "total_amount": "Gross", "tax_amount": "Tax", "subtotal": "Net", "currency": "Currency"},
}


def _invoice_rows(db: Session, org_id: str, p: dict) -> list[Invoice]:
    q = select(Invoice).join(Document, Invoice.document_id == Document.id).where(
        Invoice.organization_id == org_id, Invoice.review_status == "VERIFIED", Document.processing_status != "ARCHIVED")
    if p.get("date_from"):
        q = q.where(Invoice.invoice_date >= p["date_from"])
    if p.get("date_to"):
        q = q.where(Invoice.invoice_date <= p["date_to"])
    if p.get("invoice_ids"):
        q = q.where(Invoice.id.in_(p["invoice_ids"]))
    return list(db.scalars(q.order_by(Invoice.invoice_date, Invoice.created_at)).all())


def build_rows(db: Session, org_id: str, export_type: str, p: dict) -> list[dict]:
    rows: list[dict] = []
    if export_type in ("expense", "invoice_register"):
        for inv in _invoice_rows(db, org_id, p):
            rows.append({**{c: getattr(inv, c) for c in ("vendor_name", "invoice_number", "invoice_date", "due_date", "currency",
                                                      "subtotal", "tax_amount", "discount_amount", "total_amount", "tax_id", "category")},
                         "reconciliation_status": inv.reconciliation_status, "original_filename": inv.document.original_filename})
    elif export_type == "line_items":
        for inv in _invoice_rows(db, org_id, p):
            for li in inv.line_items:
                rows.append({"invoice_number": inv.invoice_number, "vendor_name": inv.vendor_name, "invoice_date": inv.invoice_date,
                             "currency": inv.currency, "description": li.description, "quantity": li.quantity,
                             "unit_price": li.unit_price, "tax_amount": li.tax_amount, "line_total": li.line_total})
    elif export_type == "bank_reconciliation":
        invs = {i.id: i for i in _invoice_rows(db, org_id, p)}
        if invs:
            allocs = db.scalars(select(ReconciliationAllocation).where(
                ReconciliationAllocation.organization_id == org_id, ReconciliationAllocation.invoice_id.in_(list(invs)))).all()
            for a in allocs:
                tx, inv = db.get(BankTransaction, a.bank_transaction_id), invs[a.invoice_id]
                rows.append({"invoice_number": inv.invoice_number, "vendor_name": inv.vendor_name, "invoice_total": inv.total_amount,
                             "currency": a.currency, "transaction_date": tx.transaction_date, "transaction_description": tx.description,
                             "transaction_reference": tx.reference, "allocated_amount": a.allocated_amount,
                             "reconciliation_status": inv.reconciliation_status})
    elif export_type == "duplicate_review":
        for f in db.scalars(select(DuplicateFlag).where(DuplicateFlag.organization_id == org_id).order_by(DuplicateFlag.created_at)):
            a, b = db.get(Document, f.document_id), db.get(Document, f.possible_duplicate_document_id)
            rows.append({"document": a.original_filename, "possible_duplicate_of": b.original_filename, "category": f.category,
                         "method": f.detection_method, "confidence": f.confidence_score, "review_status": f.review_status,
                         "evidence": f.evidence})
    elif export_type == "unmatched_transactions":
        alloc = tx_allocated_map(db, org_id)
        q = select(BankTransaction).where(BankTransaction.organization_id == org_id, BankTransaction.amount < 0)
        if p.get("date_from"):
            q = q.where(BankTransaction.transaction_date >= p["date_from"])
        if p.get("date_to"):
            q = q.where(BankTransaction.transaction_date <= p["date_to"])
        for t in db.scalars(q.order_by(BankTransaction.transaction_date)):
            rem = tx_remaining(t, alloc.get(t.id, Decimal(0)))
            if rem > Decimal("0.005"):
                rows.append({"transaction_date": t.transaction_date, "description": t.description, "reference": t.reference,
                             "currency": t.currency, "amount": t.amount, "unallocated_amount": rem})
    return rows


def create_export(db: Session, org_id: str, user_id: str, export_type: str, params: dict) -> tuple[ExportRecord, str]:
    spec = EXPORTS.get(export_type)
    if not spec:
        raise AppError("UNKNOWN_EXPORT_TYPE", f"Unknown export type. Choose one of: {', '.join(EXPORTS)}", 422)
    columns = params.get("columns") or [{"source": c, "header": TEMPLATES.get(params.get("template") or "generic", {}).get(c, c)}
                                       for c in spec["columns"]]
    for c in columns:
        if c["source"] not in spec["columns"]:
            raise AppError("UNKNOWN_COLUMN", f"Column '{c['source']}' is not available for this export.", 422)
    rows = build_rows(db, org_id, export_type, params)
    bad = []
    for n, r in enumerate(rows, 1):
        missing = [f for f in spec["required"] if r.get(f) in (None, "")]
        if missing:
            bad.append({"row": n, "missing": missing})
    if bad:
        raise AppError("EXPORT_VALIDATION_FAILED", f"{len(bad)} record(s) are missing required fields.", 422, {"records": bad[:20]})
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow([sanitize_cell(c["header"]) for c in columns])
    for r in rows:
        w.writerow([fmt_value(r.get(c["source"])) for c in columns])
    content = buf.getvalue().encode("utf-8-sig")
    key = get_storage().put(content)
    rec = ExportRecord(organization_id=org_id, export_type=export_type, row_count=len(rows), storage_key=key,
                       content_sha256=hashlib.sha256(content).hexdigest(), created_by=user_id,
                       filters={k: (v.isoformat() if isinstance(v, date) else v) for k, v in params.items() if v})
    db.add(rec)
    db.flush()
    log_audit(db, org_id, user_id, "export", rec.id, "export.create", None,
              {"type": export_type, "rows": len(rows), "sha256": rec.content_sha256})
    return rec, key
