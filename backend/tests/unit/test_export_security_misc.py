import io
import csv
from decimal import Decimal

import pytest

from app.core.errors import AppError
from app.core.security import RateLimiter, create_token, decode_token, hash_password, verify_password
from app.services.export_service import fmt_value, sanitize_cell
from app.services.document_service import safe_filename, sniff_mime
from tests.fixtures import docs


@pytest.mark.parametrize("v", ["=1+1", "+cmd|' /C calc'!A0", "-2+3", "@SUM(A1)", "\t=1", "\r=1"])
def test_csv_injection_is_neutralised(v):
    assert sanitize_cell(v).startswith("'")


def test_normal_text_and_numbers_untouched():
    assert sanitize_cell("ABC Supplies") == "ABC Supplies"
    assert fmt_value(Decimal("-5800.00")) == "-5800.00"  # negative money is not text
    assert fmt_value(None) == ""


def test_csv_quoting_roundtrip():
    out = io.StringIO()
    csv.writer(out).writerow([fmt_value('Acme, "Inc"\nLine2'), fmt_value("Müller GmbH")])
    assert list(csv.reader(io.StringIO(out.getvalue())))[0] == ['Acme, "Inc"\nLine2', "Müller GmbH"]


def test_password_hashing_and_tokens():
    h = hash_password("secret-pass")
    assert h != "secret-pass" and verify_password("secret-pass", h) and not verify_password("nope", h)
    assert not verify_password("x", None)
    t = create_token("u1")
    assert decode_token(t) == "u1"
    with pytest.raises(AppError):
        decode_token(t, "reset")
    with pytest.raises(AppError):
        decode_token(t + "x")


def test_rate_limiter():
    rl = RateLimiter()
    rl.check("k", 2)
    rl.check("k", 2)
    with pytest.raises(AppError) as e:
        rl.check("k", 2)
    assert e.value.status_code == 429


def test_file_signature_and_filename():
    assert sniff_mime(docs.invoice_pdf()[:16]) == "application/pdf"
    assert sniff_mime(docs.receipt_png()[:16]) == "image/png"
    assert sniff_mime(b"MZ\x90\x00 exe") is None
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("a\x00b\n.pdf") == "ab.pdf"


def test_native_pdf_skips_ocr(tmp_path):
    from app.processors.pdf_extractor import extract_document
    p = tmp_path / "a.pdf"
    p.write_bytes(docs.invoice_pdf())

    class Boom:
        def image_to_text(self, *a):
            raise AssertionError("OCR must not run for digital PDFs")

    r = extract_document(str(p), "application/pdf", provider=Boom())
    assert r.method == "NATIVE_PDF" and "INV-2026-1042" in r.text


def test_tesseract_ocr_on_scanned_image_and_pdf(tmp_path):
    from app.processors.pdf_extractor import extract_document
    for name, data, mime, method in (("r.png", docs.receipt_png(), "image/png", "OCR"),
                                     ("s.pdf", docs.scanned_pdf(), "application/pdf", "OCR")):
        p = tmp_path / name
        p.write_bytes(data)
        r = extract_document(str(p), mime)
        assert r.method == method and "450.00" in r.text and r.confidence > 0.6


def test_corrupt_files_raise_processing_errors(tmp_path):
    from app.processors.ocr_service import ProcessingError
    from app.processors.pdf_extractor import extract_document
    for name, mime in (("bad.png", "image/png"), ("bad.pdf", "application/pdf")):
        p = tmp_path / name
        p.write_bytes(b"not really a file")
        with pytest.raises(ProcessingError) as e:
            extract_document(str(p), mime)
        assert e.value.code == "UNREADABLE_DOCUMENT"
