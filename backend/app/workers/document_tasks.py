"""Document processing job. Idempotent and retry-safe: transient errors are retried with bounded exponential
backoff; permanent errors mark the job and document FAILED with a safe error code."""
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.db import session as dbs
from app.integrations.storage import get_storage
from app.models import Document, Invoice, Organization, ProcessingJob
from app.processors.invoice_parser import parse_invoice_text
from app.processors.normalize import normalize_vendor
from app.processors.ocr_service import ProcessingError
from app.processors.pdf_extractor import extract_document
from app.services import duplicate_service, invoice_service
from app.services.audit import log_audit

log = logging.getLogger("app.worker")
PARSED_FIELDS = ("vendor_name", "invoice_number", "invoice_date", "due_date", "currency", "subtotal", "tax_amount",
                 "discount_amount", "total_amount", "tax_id", "description")


def _now():
    return datetime.now(timezone.utc)


def run_job(job_id: str) -> None:
    s = get_settings()
    db = dbs.SessionLocal()
    try:
        job = db.get(ProcessingJob, job_id)
        if not job or job.status == "SUCCEEDED":
            return  # idempotent
        while job.attempts < job.max_attempts:
            job.status, job.attempts, job.started_at = "RUNNING", job.attempts + 1, job.started_at or _now()
            db.commit()
            try:
                _process(db, job)
                job.status, job.finished_at, job.error_code, job.error_message = "SUCCEEDED", _now(), None, None
                db.commit()
                return
            except ProcessingError as e:
                db.rollback()
                job = db.get(ProcessingJob, job_id)
                if e.transient and job.attempts < job.max_attempts:
                    job.error_code, job.error_message = e.code, e.message
                    db.commit()
                    time.sleep(s.job_retry_backoff_seconds * (2 ** (job.attempts - 1)))
                    continue
                _fail(db, job, e.code, e.message)
                return
            except Exception:  # unexpected: log trace, store a generic message
                db.rollback()
                log.exception("Unexpected error processing job %s", job_id)
                job = db.get(ProcessingJob, job_id)
                _fail(db, job, "INTERNAL_ERROR", "Unexpected processing error.")
                return
    finally:
        db.close()


def _fail(db, job: ProcessingJob, code: str, message: str) -> None:
    job.status, job.error_code, job.error_message, job.finished_at = "FAILED", code, message[:500], _now()
    doc = db.get(Document, job.document_id)
    if doc:
        doc.processing_status = "FAILED"
        log_audit(db, job.organization_id, None, "document", doc.id, "document.processing_failed", None, {"code": code})
    db.commit()


def _process(db, job: ProcessingJob) -> None:
    doc = db.get(Document, job.document_id)
    org = db.get(Organization, job.organization_id)
    if not doc or not org:
        raise ProcessingError("DOCUMENT_NOT_FOUND", "Document no longer exists.")
    doc.processing_status = "PROCESSING"
    db.commit()
    try:
        path = get_storage().path(doc.storage_key)
    except ValueError as e:
        raise ProcessingError("STORAGE_ERROR", "Invalid storage key.") from e
    try:
        result = extract_document(path, doc.mime_type)
    except OSError as e:
        raise ProcessingError("STORAGE_READ_ERROR", "Could not read the stored file.", transient=True) from e
    if not result.text.strip():
        raise ProcessingError("NO_TEXT_FOUND", "No readable text was found in the document.")
    parsed = parse_invoice_text(result.text, org.date_format, org.default_currency)
    doc.page_count, doc.extraction_method, doc.ocr_confidence, doc.language = (
        result.pages, result.method, round(result.confidence, 3), parsed.language)

    inv = db.scalar(select(Invoice).where(Invoice.document_id == doc.id))
    before = invoice_service.snapshot(inv) if inv else None
    if not inv:
        inv = Invoice(organization_id=doc.organization_id, document_id=doc.id)
        inv.document = doc
        db.add(inv)
    scale = 1.0 if result.method == "NATIVE_PDF" else max(0.3, min(1.0, result.confidence / 0.9))
    conf = {k: round(v * scale, 3) for k, v in parsed.confidence.items()}
    uncertain = list(parsed.uncertain)
    for k, v in conf.items():
        if v < 0.6 and k not in uncertain and getattr(parsed, k, None) is not None:
            uncertain.append(k)
    for f in PARSED_FIELDS:
        setattr(inv, f, getattr(parsed, f))
    inv.normalized_vendor_name = normalize_vendor(inv.vendor_name)
    inv.field_confidence, inv.uncertain_fields = conf, uncertain
    inv.raw_text = result.text
    inv.extraction_status, inv.review_status = "EXTRACTED", "REVIEW_REQUIRED"
    inv.payment_status = "UNKNOWN"
    invoice_service.set_line_items(inv, parsed.line_items)
    db.flush()
    inv.extraction_original = invoice_service.snapshot(inv)  # kept apart from later user corrections
    invoice_service.revalidate(inv)
    if parsed.notes:
        inv.extraction_original["notes"] = parsed.notes
    duplicate_service.detect_file_hash_duplicates(db, doc)
    duplicate_service.detect_invoice_duplicates(db, inv)
    db.flush()
    invoice_service.set_document_status(db, inv)
    log_audit(db, doc.organization_id, None, "invoice", inv.id, "invoice.extracted" if not before else "invoice.reprocessed",
              before, {"method": result.method, "confidence": round(result.confidence, 3), "warnings": len(inv.warnings or [])})
    db.commit()
