"""Provider-independent OCR interface. Tesseract is the default; Document AI / Textract adapters can implement OcrProvider."""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from PIL import Image

from app.core.config import get_settings


class ProcessingError(Exception):
    def __init__(self, code: str, message: str, transient: bool = False):
        super().__init__(message)
        self.code, self.message, self.transient = code, message, transient


@dataclass
class OcrResult:
    text: str
    confidence: float  # 0..1


class OcrProvider(ABC):
    @abstractmethod
    def image_to_text(self, image: Image.Image, languages: str) -> OcrResult: ...


class TesseractProvider(OcrProvider):
    def image_to_text(self, image: Image.Image, languages: str) -> OcrResult:
        import pytesseract
        s = get_settings()
        try:
            data = pytesseract.image_to_data(
                image, lang=languages, config="--psm 6", output_type=pytesseract.Output.DICT, timeout=s.ocr_timeout_seconds)
        except RuntimeError as e:  # pytesseract raises RuntimeError on timeout
            raise ProcessingError("OCR_TIMEOUT", "OCR timed out.", transient=True) from e
        except pytesseract.TesseractNotFoundError as e:
            raise ProcessingError("OCR_UNAVAILABLE", "Tesseract is not installed on the worker.", transient=False) from e
        except pytesseract.TesseractError as e:
            raise ProcessingError("OCR_FAILED", f"OCR failed: {str(e)[:120]}", transient=False) from e
        lines: dict[tuple, list[str]] = {}
        confs = []
        for i, word in enumerate(data["text"]):
            w = (word or "").strip()
            if not w:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(w)
            c = float(data["conf"][i])
            if c >= 0:
                confs.append(c)
        text = "\n".join(" ".join(ws) for ws in lines.values())
        return OcrResult(text=text, confidence=(sum(confs) / len(confs) / 100.0) if confs else 0.0)


def get_ocr_provider() -> OcrProvider:
    name = get_settings().ocr_provider.lower()
    if name == "tesseract":
        return TesseractProvider()
    raise ProcessingError("OCR_PROVIDER_UNKNOWN", f"Unknown OCR provider '{name}'.")
