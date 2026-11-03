"""Duplicate detection (separate from reconciliation). Never deletes anything; it only raises flags."""
from datetime import timezone

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DuplicateFlag, Invoice
from app.processors.normalize import alnum

CATEGORY_ORDER = {"EXACT": 3, "LIKELY": 2, "POSSIBLE": 1}


def _add(db: Session, doc: Document, other: Document, method: str, category: str, score: float, evidence: str) -> DuplicateFlag | None:
    pair = db.scalars(select(DuplicateFlag).where(
        DuplicateFlag.document_id == doc.id, DuplicateFlag.possible_duplicate_document_id == other.id)).all()
    if any(f.detection_method == method for f in pair):
        return None
    if method != "FILE_HASH" and any(f.detection_method == "FILE_HASH" for f in pair):
        return None  # the exact-hash flag already explains this pair; avoid noisy overlapping warnings
    flag = DuplicateFlag(organization_id=doc.organization_id, document_id=doc.id, possible_duplicate_document_id=other.id,
                         detection_method=method, category=category, confidence_score=score, evidence=evidence)
    db.add(flag)
    return flag


def detect_file_hash_duplicates(db: Session, doc: Document) -> list[DuplicateFlag]:
    others = db.scalars(select(Document).where(
        Document.organization_id == doc.organization_id, Document.content_sha256 == doc.content_sha256,
        Document.id != doc.id, Document.processing_status != "ARCHIVED")).all()
    flags = []
    for o in others:
        f = _add(db, doc, o, "FILE_HASH", "EXACT", 1.0,
                 f"Exact duplicate: the file content is identical to '{o.original_filename}' (same SHA-256).")
        if f:
            flags.append(f)
    return flags


def detect_invoice_duplicates(db: Session, inv: Invoice) -> list[DuplicateFlag]:
    """Invoice identity + fuzzy comparison. Open flags of these methods are recomputed after corrections."""
    doc = inv.document
    old = db.scalars(select(DuplicateFlag).where(
        DuplicateFlag.document_id == doc.id, DuplicateFlag.review_status == "OPEN",
        DuplicateFlag.detection_method.in_(["INVOICE_IDENTITY", "FUZZY"]))).all()
    for f in old:
        db.delete(f)
    db.flush()
    if not inv.normalized_vendor_name or inv.total_amount is None:
        return []
    others = db.scalars(select(Invoice).join(Document, Invoice.document_id == Document.id).where(
        Invoice.organization_id == inv.organization_id, Invoice.id != inv.id,
        Document.processing_status != "ARCHIVED", Invoice.total_amount.is_not(None))).all()
    flags = []
    my_no = alnum(inv.invoice_number)
    for o in others:
        if (o.currency or "") != (inv.currency or "") or o.total_amount != inv.total_amount:
            continue
        vscore = fuzz.token_set_ratio(inv.normalized_vendor_name, o.normalized_vendor_name or "")
        if vscore < 80:
            continue
        o_no = alnum(o.invoice_number)
        same_vendor = vscore >= 95
        same_no = bool(my_no) and my_no == o_no
        same_date = inv.invoice_date is not None and inv.invoice_date == o.invoice_date
        no_sim = fuzz.ratio(my_no, o_no) if my_no and o_no else None
        close_date = (inv.invoice_date and o.invoice_date and abs((inv.invoice_date - o.invoice_date).days) <= 3)
        ev_common = f"vendor '{inv.vendor_name}' ~ '{o.vendor_name}', total {inv.total_amount} {inv.currency}"
        flag = None
        if same_vendor and same_no:
            score = 0.95 if same_date else 0.85
            flag = _add(db, doc, o.document, "INVOICE_IDENTITY", "LIKELY", score,
                        f"Likely duplicate: vendor, invoice number ({inv.invoice_number}) and total match an existing record"
                        + (" and the invoice date is identical." if same_date else "; the date differs.")
                        + " The uploaded file itself differs.")
        elif no_sim is not None and no_sim < 70:
            continue  # clearly different invoice numbers: same vendor + amount is normal (e.g. recurring billing)
        elif (no_sim is not None and no_sim >= 85) or (no_sim is None and (same_date or close_date)):
            flag = _add(db, doc, o.document, "FUZZY", "POSSIBLE", round(0.5 + 0.2 * (vscore / 100), 2),
                        f"Possible duplicate: {ev_common}"
                        + (f", invoice numbers are similar ('{inv.invoice_number}' vs '{o.invoice_number}')" if no_sim else ", dates are within 3 days and one invoice number is missing")
                        + ". Evidence is incomplete; please review.")
        if flag:
            flags.append(flag)
    return flags


def open_flags(db: Session, doc_id: str) -> list[DuplicateFlag]:
    return list(db.scalars(select(DuplicateFlag).where(
        DuplicateFlag.document_id == doc_id, DuplicateFlag.review_status == "OPEN")).all())


def blocking_flags(db: Session, doc_id: str) -> list[DuplicateFlag]:
    return [f for f in open_flags(db, doc_id) if f.category in ("EXACT", "LIKELY")]
