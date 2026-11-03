"""Text extraction: native PDF text first, OCR only for pages without usable text, OCR for images."""
import io
from dataclasses import dataclass

import pymupdf
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings
from app.processors.image_preprocessor import preprocess
from app.processors.ocr_service import OcrProvider, ProcessingError, get_ocr_provider

MIN_NATIVE_CHARS = 25  # per page; fewer characters means the page is probably a scan


@dataclass
class ExtractionResult:
    text: str
    method: str  # NATIVE_PDF | OCR | MIXED
    confidence: float
    pages: int


def extract_document(path: str, mime_type: str, languages: str | None = None, provider: OcrProvider | None = None) -> ExtractionResult:
    s = get_settings()
    languages = languages or s.ocr_languages
    if mime_type == "application/pdf":
        return _extract_pdf(path, languages, provider)
    return _extract_image(path, languages, provider)


def _extract_image(path: str, languages: str, provider: OcrProvider | None) -> ExtractionResult:
    try:
        with open(path, "rb") as f:
            img = Image.open(io.BytesIO(f.read()))
            img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ProcessingError("UNREADABLE_DOCUMENT", "The image could not be decoded.") from e
    res = (provider or get_ocr_provider()).image_to_text(preprocess(img), languages)
    return ExtractionResult(res.text, "OCR", res.confidence, 1)


def _extract_pdf(path: str, languages: str, provider: OcrProvider | None) -> ExtractionResult:
    s = get_settings()
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        raise ProcessingError("UNREADABLE_DOCUMENT", "The PDF could not be opened.") from e
    with doc:
        if doc.needs_pass or doc.is_encrypted:
            raise ProcessingError("ENCRYPTED_PDF", "Password-protected PDFs are not supported.")
        if doc.page_count > s.max_pages:
            raise ProcessingError("PAGE_LIMIT_EXCEEDED", f"Document has {doc.page_count} pages; the limit is {s.max_pages}.")
        texts, confs, used_ocr, used_native = [], [], False, False
        for page in doc:
            native = page.get_text("text") or ""
            if len(native.strip()) >= MIN_NATIVE_CHARS:
                texts.append(native)
                confs.append(1.0)
                used_native = True
                continue
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            res = (provider or get_ocr_provider()).image_to_text(preprocess(img), languages)
            texts.append(res.text)
            confs.append(res.confidence)
            used_ocr = True
        method = "MIXED" if used_ocr and used_native else ("OCR" if used_ocr else "NATIVE_PDF")
        return ExtractionResult("\n".join(texts), method, sum(confs) / max(len(confs), 1), doc.page_count)
