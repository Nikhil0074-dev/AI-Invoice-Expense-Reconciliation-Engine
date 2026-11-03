from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BankTransaction, Document, DuplicateFlag, Invoice, Organization
from app.services.reconciliation_service import tx_allocated_map, tx_remaining


def build_dashboard(db: Session, org: Organization, date_from=None, date_to=None) -> dict:
    cur = org.default_currency
    docs = db.scalars(select(Document).where(Document.organization_id == org.id)).all()
    active = [d for d in docs if d.processing_status != "ARCHIVED"]
    q = select(Invoice).join(Document, Invoice.document_id == Document.id).where(
        Invoice.organization_id == org.id, Document.processing_status != "ARCHIVED")
    if date_from:
        q = q.where(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.where(Invoice.invoice_date <= date_to)
    invoices = db.scalars(q).all()
    verified = [i for i in invoices if i.review_status == "VERIFIED" and i.total_amount is not None]
    main = [i for i in verified if i.currency == cur]
    other = defaultdict(Decimal)
    for i in verified:
        if i.currency != cur:
            other[i.currency or "?"] += i.total_amount

    monthly, vendors, cats = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    for i in main:
        if i.invoice_date:
            monthly[i.invoice_date.strftime("%Y-%m")] += i.total_amount
        vendors[i.vendor_name or "Unknown"] += i.total_amount
        cats[i.category or "Uncategorized"] += i.total_amount
    reconciled = sum((i.total_amount for i in main if i.reconciliation_status == "CONFIRMED"), Decimal(0))
    partial = sum((i.total_amount for i in main if i.reconciliation_status == "PARTIALLY_RECONCILED"), Decimal(0))
    total_main = sum((i.total_amount for i in main), Decimal(0))

    alloc = tx_allocated_map(db, org.id)
    txs = db.scalars(select(BankTransaction).where(BankTransaction.organization_id == org.id, BankTransaction.amount < 0)).all()
    unmatched = sum(1 for t in txs if tx_remaining(t, alloc.get(t.id, Decimal(0))) > Decimal("0.005"))
    open_dups = db.scalar(select(func.count(DuplicateFlag.id)).where(
        DuplicateFlag.organization_id == org.id, DuplicateFlag.review_status == "OPEN")) or 0

    trend = defaultdict(lambda: {"uploaded": 0, "failed": 0, "needs_review": 0})
    for d in active:
        k = d.created_at.strftime("%Y-%m")
        trend[k]["uploaded"] += 1
        if d.processing_status == "FAILED":
            trend[k]["failed"] += 1
        if d.processing_status in ("REVIEW_REQUIRED", "DUPLICATE_REVIEW"):
            trend[k]["needs_review"] += 1

    f = lambda v: format(v, "f")
    return {
        "currency": cur,
        "cards": {
            "total_invoices": len(active),
            "total_expenses": f(total_main),
            "other_currency_expenses": {k: f(v) for k, v in other.items()},
            "awaiting_review": sum(1 for d in active if d.processing_status in ("REVIEW_REQUIRED", "DUPLICATE_REVIEW")),
            "reconciled_expenses": f(reconciled),
            "unmatched_transactions": unmatched,
            "potential_duplicates": open_dups,
            "ocr_failures": sum(1 for d in docs if d.processing_status == "FAILED"),
        },
        "monthly_expenses": [{"month": k, "total": float(v)} for k, v in sorted(monthly.items())],
        "spend_by_vendor": [{"vendor": k, "total": float(v)} for k, v in sorted(vendors.items(), key=lambda x: -x[1])[:8]],
        "spend_by_category": [{"category": k, "total": float(v)} for k, v in sorted(cats.items(), key=lambda x: -x[1])],
        "reconciliation_split": [
            {"name": "Reconciled", "total": float(reconciled)},
            {"name": "Partially reconciled", "total": float(partial)},
            {"name": "Unreconciled", "total": float(total_main - reconciled - partial)},
        ],
        "processing_trend": [{"month": k, **v} for k, v in sorted(trend.items())],
    }
