from sqlalchemy import select

from app.db import session as dbs
from app.models import AuditLog, Document, ProcessingJob
from tests.conftest import upload_and_verify
from tests.fixtures import docs


def test_upload_extracts_review_and_audit(admin):
    r = admin.upload(docs.invoice_pdf())
    assert r.status_code == 201 and r.json()["document_id"]
    doc = admin.get(f"/documents/{r.json()['document_id']}").json()
    assert doc["processing_status"] == "REVIEW_REQUIRED" and doc["extraction_method"] == "NATIVE_PDF"
    assert doc["vendor_name"] == "ABC Office Supplies" and doc["total_amount"] == "5800.0000" or doc["total_amount"] == "5800.00"
    inv = admin.get(f"/invoices/{doc['invoice_id']}").json()
    assert inv["invoice_number"] == "INV-2026-1042" and inv["invoice_date"] == "2026-10-12" and inv["currency"] == "INR"
    assert inv["review_status"] == "REVIEW_REQUIRED" and len(inv["line_items"]) == 1
    assert inv["extraction_original"]["total_amount"] in ("5800.00", "5800.0000", "5800")
    job = admin.get(f"/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "SUCCEEDED" and job["attempts"] == 1


def test_correction_preserves_original_and_audits(admin):
    r = admin.upload(docs.invoice_pdf())
    inv_id = admin.get(f"/documents/{r.json()['document_id']}").json()["invoice_id"]
    p = admin.patch(f"/invoices/{inv_id}", json={"vendor_name": "ABC Office Supplies Pvt Ltd", "total_amount": "5801.00"})
    assert p.status_code == 200
    inv = p.json()
    assert inv["vendor_name"].endswith("Pvt Ltd") and inv["extraction_original"]["vendor_name"] == "ABC Office Supplies"
    assert any(w["code"] == "TOTAL_MISMATCH" for w in inv["warnings"])
    logs = admin.get(f"/audit-logs?entity_type=invoice&entity_id={inv_id}").json()
    corr = next(x for x in logs if x["action"] == "invoice.correct")
    assert corr["before_state"]["vendor_name"] == "ABC Office Supplies" and corr["after_state"]["total_amount"].startswith("5801")
    assert corr["actor_name"] == "admin"


def test_backend_validation_of_corrections(admin):
    inv_id = admin.get(f"/documents/{admin.upload(docs.invoice_pdf()).json()['document_id']}").json()["invoice_id"]
    assert admin.patch(f"/invoices/{inv_id}", json={"currency": "ZZZ"}).status_code == 422
    assert admin.patch(f"/invoices/{inv_id}", json={"total_amount": "-5"}).status_code == 422
    assert admin.patch(f"/invoices/{inv_id}", json={"total_amount": "12.345"}).status_code == 422
    assert admin.patch(f"/invoices/{inv_id}", json={"invoice_date": "1800-01-01"}).status_code == 422
    assert admin.patch(f"/invoices/{inv_id}", json={"invoice_date": "not-a-date"}).status_code == 422


def test_verify_gates(admin):
    inv = admin.get(f"/documents/{admin.upload(docs.mismatched_total_pdf()).json()['document_id']}").json()["invoice_id"]
    r = admin.post(f"/invoices/{inv}/verify", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "WARNINGS_NOT_ACKNOWLEDGED"
    assert admin.post(f"/invoices/{inv}/verify", json={"acknowledge_warnings": True}).json()["review_status"] == "VERIFIED"
    # missing required fields block verification outright
    inv2 = admin.get(f"/documents/{admin.upload(docs._pdf(['just words 123'])).json()['document_id']}").json()["invoice_id"]
    r = admin.post(f"/invoices/{inv2}/verify", json={"acknowledge_warnings": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VERIFICATION_BLOCKED"
    admin.patch(f"/invoices/{inv2}", json={"vendor_name": "V", "invoice_date": "2026-10-01", "currency": "INR", "total_amount": "10"})
    assert admin.post(f"/invoices/{inv2}/verify", json={"acknowledge_warnings": True}).status_code == 200


def test_editing_verified_invoice_reopens_review(admin):
    inv_id, _ = upload_and_verify(admin, docs.invoice_pdf())
    assert admin.get(f"/invoices/{inv_id}").json()["document_status"] == "READY_FOR_RECONCILIATION"
    admin.patch(f"/invoices/{inv_id}", json={"category": "Office"})  # soft field: stays verified
    assert admin.get(f"/invoices/{inv_id}").json()["review_status"] == "VERIFIED"
    inv = admin.patch(f"/invoices/{inv_id}", json={"total_amount": "5801"}).json()
    assert inv["review_status"] == "REVIEW_REQUIRED" and inv["document_status"] == "REVIEW_REQUIRED"


def test_ambiguous_date_currency_and_missing_number_are_flagged(admin):
    inv = admin.get(f"/documents/{admin.upload(docs.ambiguous_date_pdf()).json()['document_id']}").json()["invoice_id"]
    d = admin.get(f"/invoices/{inv}").json()
    assert "invoice_date" in d["uncertain_fields"] and "Uncertain invoice date" in d["review_reasons"]
    inv = admin.get(f"/documents/{admin.upload(docs.missing_number_pdf()).json()['document_id']}").json()["invoice_id"]
    assert "Missing invoice number" in admin.get(f"/invoices/{inv}").json()["review_reasons"]
    inv = admin.get(f"/documents/{admin.upload(docs.german_invoice_pdf()).json()['document_id']}").json()["invoice_id"]
    d = admin.get(f"/invoices/{inv}").json()
    assert d["currency"] == "EUR" and d["total_amount"].startswith("1190") and d["invoice_date"] == "2026-10-12"


def test_scanned_receipt_goes_through_ocr(admin):
    doc = admin.get(f"/documents/{admin.upload(docs.receipt_png(), 'r.png', 'image/png').json()['document_id']}").json()
    assert doc["extraction_method"] == "OCR" and doc["ocr_confidence"] > 0.6
    assert doc["vendor_name"] == "CHAI POINT CAFE" and doc["total_amount"].startswith("450")
    doc = admin.get(f"/documents/{admin.upload(docs.scanned_pdf(), 's.pdf').json()['document_id']}").json()
    assert doc["extraction_method"] == "OCR" and doc["total_amount"].startswith("450")


def test_upload_validation(admin):
    r = admin.upload(b"MZ\x90\x00 this is an exe", "invoice.pdf")  # extension lies, signature does not
    assert r.status_code == 400 and r.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert admin.upload(b"", "x.pdf").status_code == 400
    r = admin.upload(docs.malicious_pdf(), "evil.pdf")
    assert r.status_code == 400 and r.json()["error"]["code"] == "ACTIVE_CONTENT_REJECTED"
    admin.patch(f"/organizations/{admin.org_id}", json={"max_upload_mb": 1})
    r = admin.upload(docs.invoice_pdf() + b"0" * (1024 * 1024 + 10), "big.pdf")
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert admin.get("/documents").json()["total"] == 0


def test_failed_processing_is_recorded_and_retry_works(admin):
    bad = docs.invoice_pdf()[:5] + b"corrupt-not-a-real-pdf" * 20
    r = admin.upload(bad, "bad.pdf")
    assert r.status_code == 201
    doc = admin.get(f"/documents/{r.json()['document_id']}").json()
    assert doc["processing_status"] == "FAILED"
    job = admin.get(f"/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "FAILED" and job["error_code"] == "UNREADABLE_DOCUMENT" and job["attempts"] == 1  # permanent: not retried
    assert "Traceback" not in str(job)
    assert admin.get("/dashboard").json()["cards"]["ocr_failures"] == 1


def test_transient_errors_are_retried_with_bound(admin, monkeypatch):
    from app.processors.ocr_service import ProcessingError
    from app.workers import document_tasks
    calls = {"n": 0}
    real = document_tasks.extract_document

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProcessingError("OCR_TIMEOUT", "timeout", transient=True)
        return real(*a, **k)

    monkeypatch.setattr(document_tasks, "extract_document", flaky)
    r = admin.upload(docs.invoice_pdf())
    assert admin.get(f"/jobs/{r.json()['job_id']}").json()["attempts"] == 3
    assert admin.get(f"/documents/{r.json()['document_id']}").json()["processing_status"] == "REVIEW_REQUIRED"
    monkeypatch.setattr(document_tasks, "extract_document", lambda *a, **k: (_ for _ in ()).throw(ProcessingError("OCR_TIMEOUT", "t", True)))
    r = admin.upload(docs.invoice_pdf(number="INV-9"))
    job = admin.get(f"/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "FAILED" and job["attempts"] == job["max_attempts"] == 3


def test_reprocess_and_job_idempotency(admin):
    r = admin.upload(docs.invoice_pdf())
    doc_id = r.json()["document_id"]
    inv_id = admin.get(f"/documents/{doc_id}").json()["invoice_id"]
    admin.patch(f"/invoices/{inv_id}", json={"vendor_name": "Edited"})
    assert admin.post(f"/documents/{doc_id}/process").status_code == 202
    inv = admin.get(f"/invoices/{inv_id}").json()
    assert inv["vendor_name"] == "ABC Office Supplies" and inv["id"] == inv_id  # same record, re-extracted
    from app.workers.document_tasks import run_job
    run_job(r.json()["job_id"])  # already succeeded -> no-op
    assert admin.get("/invoices").json()["total"] == 1


def test_preview_download_headers_and_delete(admin):
    doc_id = admin.upload(docs.invoice_pdf()).json()["document_id"]
    p = admin.get(f"/documents/{doc_id}/preview")
    assert p.status_code == 200 and p.headers["content-type"] == "application/pdf" and p.headers["x-content-type-options"] == "nosniff"
    assert p.content[:5] == b"%PDF-"
    assert admin.c.get(f"/api/v1/documents/{doc_id}/preview").status_code == 401
    assert admin.delete(f"/documents/{doc_id}").status_code == 204
    assert admin.get(f"/documents/{doc_id}").status_code == 404


def test_document_search_filter_and_pagination(admin):
    admin.upload(docs.invoice_pdf())
    admin.upload(docs.invoice_pdf("Zeta Travel", "ZT-1", "03 Oct 2026", None, "USD", (("Flight", 1, "300.00", "300.00"),), "300.00", "", "", "300.00"), "z.pdf")
    assert admin.get("/documents?q=zeta").json()["total"] == 1
    assert admin.get("/documents?q=INV-2026").json()["total"] == 1
    assert admin.get("/documents?currency=usd").json()["total"] == 1
    assert admin.get("/documents?status=REVIEW_REQUIRED").json()["total"] == 2
    assert admin.get("/documents?page_size=1&page=2").json()["items"].__len__() == 1
    assert admin.get("/documents?date_from=2026-10-10").json()["total"] == 1
    assert admin.get("/documents?sort=amount&direction=asc").json()["items"][0]["vendor_name"] == "Zeta Travel"
    assert admin.get("/documents?page_size=1000").status_code == 422
