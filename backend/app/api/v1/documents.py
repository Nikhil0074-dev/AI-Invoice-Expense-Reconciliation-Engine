from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Ctx, require
from app.core.errors import AppError
from app.integrations.storage import get_storage
from app.models import Document, DuplicateFlag, Invoice, ProcessingJob, ReconciliationMatch
from app.schemas import DocumentOut, JobOut, UploadOut
from app.services import document_service, invoice_service
from app.services.audit import log_audit

router = APIRouter(tags=["documents"])


def _out(d: Document, open_flags: int = 0) -> DocumentOut:
    out = DocumentOut.model_validate(d)
    inv = d.invoice
    if inv:
        out.invoice_id, out.vendor_name, out.invoice_number = inv.id, inv.vendor_name, inv.invoice_number
        out.currency, out.total_amount, out.invoice_date = inv.currency, inv.total_amount, inv.invoice_date
    out.open_duplicate_flags = open_flags
    return out


def _flag_counts(db: Session, org_id: str) -> dict[str, int]:
    rows = db.execute(select(DuplicateFlag.document_id, func.count()).where(
        DuplicateFlag.organization_id == org_id, DuplicateFlag.review_status == "OPEN").group_by(DuplicateFlag.document_id)).all()
    return dict(rows)


def get_doc(ctx: Ctx, doc_id: str) -> Document:
    d = ctx.db.scalar(select(Document).where(Document.id == doc_id, Document.organization_id == ctx.org.id))
    if not d:
        raise AppError("DOCUMENT_NOT_FOUND", "Document not found.", 404)
    return d


@router.post("/documents", response_model=UploadOut, status_code=201)
async def upload_document(background: BackgroundTasks, file: UploadFile = File(...), ctx: Ctx = Depends(require("documents:upload"))):
    doc, job = await document_service.create_document(ctx.db, ctx.org, ctx.user.id, file, background)
    ctx.db.refresh(doc)
    return UploadOut(document_id=doc.id, job_id=job.id, processing_status=doc.processing_status)


@router.get("/documents")
def list_documents(q: str | None = None, status: str | None = None, currency: str | None = None,
                   date_from: date | None = None, date_to: date | None = None, min_amount: float | None = None,
                   max_amount: float | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                   sort: str = "created_at", direction: str = "desc", ctx: Ctx = Depends(require("documents:read"))):
    db = ctx.db
    stmt = select(Document).outerjoin(Invoice, Invoice.document_id == Document.id).where(Document.organization_id == ctx.org.id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Document.original_filename.ilike(like), Invoice.vendor_name.ilike(like), Invoice.invoice_number.ilike(like)))
    if status:
        stmt = stmt.where(Document.processing_status == status)
    if currency:
        stmt = stmt.where(Invoice.currency == currency.upper())
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    if min_amount is not None:
        stmt = stmt.where(Invoice.total_amount >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(Invoice.total_amount <= max_amount)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    cols = {"created_at": Document.created_at, "vendor": Invoice.vendor_name, "amount": Invoice.total_amount,
            "invoice_date": Invoice.invoice_date, "status": Document.processing_status, "filename": Document.original_filename}
    col = cols.get(sort, Document.created_at)
    stmt = stmt.order_by(col.asc() if direction == "asc" else col.desc()).offset((page - 1) * page_size).limit(page_size)
    flags = _flag_counts(db, ctx.org.id)
    items = [_out(d, flags.get(d.id, 0)) for d in db.scalars(stmt).all()]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: str, ctx: Ctx = Depends(require("documents:read"))):
    d = get_doc(ctx, doc_id)
    return _out(d, _flag_counts(ctx.db, ctx.org.id).get(d.id, 0))


def _file_response(d: Document, disposition: str) -> FileResponse:
    path = get_storage().path(d.storage_key)
    return FileResponse(path, media_type=d.mime_type, headers={
        "Content-Disposition": f'{disposition}; filename="{d.original_filename.encode("ascii", "ignore").decode() or "document"}"',
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.get("/documents/{doc_id}/preview")
def preview_document(doc_id: str, ctx: Ctx = Depends(require("documents:read"))):
    return _file_response(get_doc(ctx, doc_id), "inline")


@router.get("/documents/{doc_id}/download")
def download_document(doc_id: str, ctx: Ctx = Depends(require("documents:read"))):
    return _file_response(get_doc(ctx, doc_id), "attachment")


@router.post("/documents/{doc_id}/process", response_model=UploadOut, status_code=202)
def reprocess(doc_id: str, background: BackgroundTasks, ctx: Ctx = Depends(require("documents:process"))):
    d = get_doc(ctx, doc_id)
    db = ctx.db
    if d.processing_status in ("QUEUED", "PROCESSING"):
        raise AppError("ALREADY_PROCESSING", "This document is already being processed.", 409)
    if d.invoice and invoice_service.has_allocations(db, d.invoice.id):
        raise AppError("INVOICE_RECONCILED", "Unlink the reconciliation before reprocessing this document.", 409)
    if d.invoice:
        for m in db.scalars(select(ReconciliationMatch).where(ReconciliationMatch.invoice_id == d.invoice.id,
                                                              ReconciliationMatch.match_status.in_(["SUGGESTED", "NEEDS_REVIEW"]))):
            db.delete(m)
        d.invoice.reconciliation_status = "UNMATCHED"
    d.processing_status = "QUEUED"
    from app.core.config import get_settings
    job = ProcessingJob(organization_id=ctx.org.id, document_id=d.id, max_attempts=get_settings().job_max_attempts)
    db.add(job)
    log_audit(db, ctx.org.id, ctx.user.id, "document", d.id, "document.reprocess")
    db.commit()
    document_service.enqueue(job.id, background)
    db.refresh(d)
    return UploadOut(document_id=d.id, job_id=job.id, processing_status=d.processing_status, message="Processing queued.")


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, ctx: Ctx = Depends(require("documents:delete"))):
    d = get_doc(ctx, doc_id)
    if d.invoice and invoice_service.has_allocations(ctx.db, d.invoice.id):
        raise AppError("INVOICE_RECONCILED", "This document is part of a reconciliation. Unlink it first.", 409)
    log_audit(ctx.db, ctx.org.id, ctx.user.id, "document", d.id, "document.delete", {"filename": d.original_filename}, None)
    key = d.storage_key
    ctx.db.delete(d)
    ctx.db.commit()
    get_storage().delete(key)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, ctx: Ctx = Depends(require("documents:read"))):
    j = ctx.db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.organization_id == ctx.org.id))
    if not j:
        raise AppError("JOB_NOT_FOUND", "Job not found.", 404)
    return j
