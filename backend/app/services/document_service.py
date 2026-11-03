import hashlib
import os
import re

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.integrations.storage import get_storage
from app.models import Document, Organization, ProcessingJob
from app.services import duplicate_service
from app.services.audit import log_audit

SIGNATURES = [(b"%PDF-", "application/pdf"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg")]
ACTIVE_CONTENT = (b"/JavaScript", b"/Launch", b"/EmbeddedFile")


def sniff_mime(head: bytes) -> str | None:
    for sig, mime in SIGNATURES:
        if head.startswith(sig):
            return mime
    return None


def safe_filename(name: str | None) -> str:
    base = os.path.basename((name or "upload").replace("\\", "/"))
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip() or "upload"
    return base[:200]


def scan_upload(data: bytes, mime: str) -> None:
    """Basic defence-in-depth. Integrate ClamAV or a similar scanner here for production."""
    if mime == "application/pdf" and any(tok in data for tok in ACTIVE_CONTENT):
        raise AppError("ACTIVE_CONTENT_REJECTED", "PDFs with embedded scripts, launch actions or attachments are not accepted.", 400)


async def read_limited(file: UploadFile, limit_bytes: int) -> bytes:
    chunks, size = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > limit_bytes:
            raise AppError("FILE_TOO_LARGE", f"File exceeds the {limit_bytes // (1024 * 1024)} MB limit.", 413)
        chunks.append(chunk)
    return b"".join(chunks)


async def create_document(db: Session, org: Organization, user_id: str, file: UploadFile, background: BackgroundTasks) -> tuple[Document, ProcessingJob]:
    s = get_settings()
    limit = min(org.max_upload_mb, s.max_upload_mb) * 1024 * 1024
    data = await read_limited(file, limit)
    if not data:
        raise AppError("EMPTY_FILE", "The uploaded file is empty.", 400)
    mime = sniff_mime(data[:16])
    if not mime:
        raise AppError("UNSUPPORTED_FILE_TYPE", "Only PDF, JPEG and PNG documents are supported (file signature check failed).", 400)
    scan_upload(data, mime)
    key = get_storage().put(data)
    doc = Document(organization_id=org.id, uploaded_by=user_id, original_filename=safe_filename(file.filename), storage_key=key,
                   content_sha256=hashlib.sha256(data).hexdigest(), mime_type=mime, file_size_bytes=len(data),
                   processing_status="QUEUED")
    db.add(doc)
    db.flush()
    job = ProcessingJob(organization_id=org.id, document_id=doc.id, max_attempts=s.job_max_attempts)
    db.add(job)
    log_audit(db, org.id, user_id, "document", doc.id, "document.upload", None, {"filename": doc.original_filename, "sha256": doc.content_sha256})
    db.commit()
    enqueue(job.id, background)
    return doc, job


def enqueue(job_id: str, background: BackgroundTasks | None) -> None:
    from app.workers.document_tasks import run_job
    mode = get_settings().processing_mode
    if mode == "celery":
        from app.workers.celery_app import process_document_job
        process_document_job.delay(job_id)
    elif mode == "inline" or background is None:
        run_job(job_id)
    else:
        background.add_task(run_job, job_id)
