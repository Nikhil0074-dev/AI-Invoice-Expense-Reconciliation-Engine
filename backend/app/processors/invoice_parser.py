"""Rule-based invoice field extraction (English, German, French, Spanish labels).

Principles: never guess silently. Every extracted field gets a confidence and anything
heuristic, ambiguous or missing is listed in `uncertain` so the review UI can highlight it.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.processors.normalize import (
    alternate_reading, detect_currency, detect_decimal_style, parse_amount, parse_date, quantize_money,
)

NUM = r"-?\(?\d[\d.,\u00a0\u202f']*\d\)?|\d"
AMOUNT_RE = re.compile(NUM)

LABELS = {
    "invoice_date": r"invoice\s*date|date\s*of\s*issue|issue\s*date|bill\s*date|rechnungsdatum|ausstellungsdatum|date\s*de\s*facture|date\s*d.[ée]mission|fecha\s*de\s*factura|fecha\s*de\s*emisi[oó]n|fecha|datum|date",
    "due_date": r"due\s*date|payment\s*due|due\s*on|pay\s*by|f[äa]lligkeitsdatum|f[äa]llig\s*am|zahlbar\s*bis|date\s*d.[ée]ch[ée]ance|[ée]ch[ée]ance|fecha\s*de\s*vencimiento|vencimiento",
    "total_strong": r"grand\s*total|total\s*amount|total\s*payable|total\s*invoice|invoice\s*total|gesamtbetrag|gesamtsumme|endbetrag|rechnungsbetrag|total\s*ttc|montant\s*total|importe\s*total|total\s*a\s*pagar",
    "total_plain": r"total|summe|gesamt|total\s*general",
    "total_due": r"amount\s*due|balance\s*due|total\s*due",
    "subtotal": r"sub\s*-?\s*total|zwischensumme|nettobetrag|netto|total\s*ht|sous-total|base\s*imponible|net\s*amount",
    "tax_total": r"total\s*tax|tax\s*amount|total\s*gst|total\s*vat|steuerbetrag|gesamt\s*mwst|montant\s*tva|total\s*iva|cuota\s*iva",
    "tax_part": r"cgst|sgst|igst|utgst|gst|vat|sales\s*tax|tax|mwst\.?|ust\.?|umsatzsteuer|tva|iva",
    "discount": r"discount|rabatt|remise|descuento|less",
}
INV_NO_RE = re.compile(
    r"(?:invoice|inv|bill|receipt|rechnung(?:s)?|facture|factura)\s*(?:no|nr|num|number|nummer|n[°o]|n[úu]mero|#)\b\.?\s*[:#\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/_.]{1,30})",
    re.I)
INV_HASH_RE = re.compile(r"(?:invoice|rechnung|facture|factura)\s*#\s*([A-Za-z0-9][A-Za-z0-9\-/_.]{1,30})", re.I)
INV_FALLBACK_RE = re.compile(r"\b((?:INV|RE|R|BILL)[-/]?[A-Z0-9]*\d[A-Z0-9\-/]*)\b")
GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
VAT_RE = re.compile(r"(?:vat|tax|ust|tva|nif|cif)[\s\-]*(?:id|no|nr|number|reg|idnr)?\.?\s*[:#]?\s*([A-Z]{2}\s?[A-Z0-9]{8,12})\b", re.I)
VENDOR_LABEL_RE = re.compile(r"^(?:from|vendor|seller|supplier|sold\s*by|lieferant|verk[äa]ufer|fournisseur|proveedor)\s*[:\-]\s*(.+)$", re.I)
VENDOR_SKIP = re.compile(
    r"^(tax\s*invoice|invoice|bill|receipt|rechnung|facture|factura|original|duplicate|copy|page|seite|date|datum|"
    r"bill\s*to|ship\s*to|customer|to:|www\.|http|tel|phone|email|e-mail|gstin|vat|ust|invoice\s*(no|number|date)|"
    r"cash\s*memo|thank|description|qty|item|sr\.?\s*no)\b", re.I)

LANG_HINTS = {
    "de": ["rechnung", "datum", "summe", "betrag", "mwst", "gesamt", "zwischensumme", "netto"],
    "fr": ["facture", "date", "montant", "tva", "total ttc", "échéance"],
    "es": ["factura", "fecha", "importe", "iva", "vencimiento"],
    "en": ["invoice", "total", "date", "tax", "amount", "subtotal", "due"],
}


@dataclass
class ParsedInvoice:
    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax_amount: Decimal | None = None
    discount_amount: Decimal | None = None
    total_amount: Decimal | None = None
    tax_id: str | None = None
    description: str | None = None
    line_items: list[dict] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)
    uncertain: list[str] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    language: str = "unknown"
    decimal_style: str | None = None


def detect_language(text: str) -> str:
    low = text.lower()
    scores = {lang: sum(low.count(w) for w in words) for lang, words in LANG_HINTS.items()}
    for lang in ("de", "fr", "es"):
        if scores[lang] >= 3 and scores[lang] >= scores["en"] * 0.8:
            return lang
    return "en" if scores["en"] >= 2 else "unknown"


def _amounts_in(line: str, hint: str | None) -> list[Decimal]:
    out = []
    for m in AMOUNT_RE.finditer(line):
        tail = line[m.end():m.end() + 2].strip()
        if tail.startswith("%"):
            continue
        before = line[max(0, m.start() - 1):m.start()]
        if before == "@":
            continue
        raw = m.group(0)
        d = parse_amount(raw, hint)
        if d is not None:
            out.append(d)
    return out


def _value_for(lines: list[str], i: int, hint: str | None) -> Decimal | None:
    """Amount on label line (last non-percent number) or on the next line(s) for table-style PDFs."""
    vals = _amounts_in(re.sub(r"^[^\d\u20b9€£$-]*?(?=[:\s])", "", lines[i], count=1) if False else lines[i], hint)
    if vals:
        return vals[-1]
    for j in (i + 1, i + 2):
        if j < len(lines):
            nxt = lines[j].strip()
            if re.fullmatch(r"[^\w]*(?:[A-Z]{3}\s*)?[\u20b9€£$]?\s*(?:" + NUM + r")\s*(?:[A-Z]{3}|[\u20b9€£$])?", nxt):
                v = _amounts_in(nxt, hint)
                if v:
                    return v[-1]
    return None


def _find_label_line(lines: list[str], label_re: str, exclude: str | None = None):
    pat = re.compile(r"(?:^|\b)(?:" + label_re + r")\b", re.I)
    for i, ln in enumerate(lines):
        m = pat.search(ln)
        if m and (exclude is None or not re.search(exclude, ln, re.I)):
            yield i, ln, m


def parse_invoice_text(text: str, date_format: str = "DMY", default_currency: str | None = None) -> ParsedInvoice:
    p = ParsedInvoice()
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    p.language = detect_language(text)
    num_tokens = [m.group(0) for m in AMOUNT_RE.finditer(text) if re.search(r"[.,]\d{1,2}$", m.group(0))]
    p.decimal_style = detect_decimal_style(num_tokens)
    hint = p.decimal_style

    # ---- currency
    cur, amb = detect_currency(text)
    if cur:
        p.currency = cur
        p.confidence["currency"] = 0.55 if amb else 0.9
        if amb:
            p.uncertain.append("currency")
            p.notes["currency"] = "Currency symbol or several currency codes found; please confirm."
    p.currency_detected = cur is not None  # type: ignore[attr-defined]

    # ---- invoice number
    m = INV_NO_RE.search(text) or INV_HASH_RE.search(text)
    if m and re.search(r"\d", m.group(1)):
        p.invoice_number = m.group(1).strip(".-/_")
        p.confidence["invoice_number"] = 0.92
    else:
        m = INV_FALLBACK_RE.search(text)
        if m:
            p.invoice_number = m.group(1)
            p.confidence["invoice_number"] = 0.55
            p.uncertain.append("invoice_number")

    # ---- dates
    due_pat, inv_pat = LABELS["due_date"], LABELS["invoice_date"]
    for i, ln, mm in _find_label_line(lines, due_pat):
        seg = ln[mm.end():] or (lines[i + 1] if i + 1 < len(lines) else "")
        d, ambiguous = parse_date(seg or (lines[i + 1] if i + 1 < len(lines) else ""), date_format)
        if d:
            p.due_date = d
            p.confidence["due_date"] = 0.5 if ambiguous else 0.88
            if ambiguous:
                p.uncertain.append("due_date")
            break
    strong_inv = r"invoice\s*date|date\s*of\s*issue|issue\s*date|bill\s*date|rechnungsdatum|ausstellungsdatum|date\s*de\s*facture|date\s*d.[ée]mission|fecha\s*de\s*factura|fecha\s*de\s*emisi[oó]n"
    for label, conf in ((strong_inv, 0.92), (inv_pat, 0.75)):
        found = False
        for i, ln, mm in _find_label_line(lines, label, exclude=due_pat):
            seg = ln[mm.end():]
            if not parse_date(seg, date_format)[0] and i + 1 < len(lines):
                seg = lines[i + 1]
            d, ambiguous = parse_date(seg, date_format)
            if d:
                p.invoice_date = d
                p.confidence["invoice_date"] = 0.5 if ambiguous else conf
                if ambiguous:
                    p.uncertain.append("invoice_date")
                    p.notes["invoice_date"] = f"Ambiguous date format ({alternate_reading(seg, date_format)}); verify."
                found = True
                break
        if found:
            break
    if not p.invoice_date:
        for ln in lines:
            if re.search(due_pat, ln, re.I):
                continue
            d, ambiguous = parse_date(ln, date_format)
            if d:
                p.invoice_date = d
                p.confidence["invoice_date"] = 0.45
                p.uncertain.append("invoice_date")
                p.notes["invoice_date"] = "Date found without an 'invoice date' label; verify."
                break

    # ---- amounts
    def first_amount(label_key: str, exclude: str | None = None):
        for i, ln, mm in _find_label_line(lines, LABELS[label_key], exclude):
            v = _value_for(lines, i, hint)
            if v is not None:
                return v
        return None

    not_total = r"total\s*(?:tax|discount|qty|quantity|items|vat|gst|savings|ht)\b|sub\s*-?\s*total|zwischensumme|^\s*(?:sub)"
    total = None
    conf_total = 0.0
    for key, conf, excl in (("total_strong", 0.93, None), ("total_plain", 0.85, not_total), ("total_due", 0.6, None)):
        cands = []
        for i, ln, mm in _find_label_line(lines, LABELS[key], excl):
            if key == "total_plain" and re.search(r"sub\s*-?\s*total|zwischensumme|total\s*(tax|discount)", ln, re.I):
                continue
            v = _value_for(lines, i, hint)
            if v is not None:
                cands.append(v)
        if cands:
            total, conf_total = cands[-1], conf
            if key == "total_due":
                p.uncertain.append("total_amount")
                p.notes["total_amount"] = "Only an 'amount due' figure was found; it may exclude prior payments."
            break
    if total is not None:
        p.total_amount, p.confidence["total_amount"] = abs(total), conf_total
    sub = first_amount("subtotal")
    if sub is not None:
        p.subtotal, p.confidence["subtotal"] = abs(sub), 0.88

    # tax: explicit total > CGST+SGST/IGST > single labelled line
    tax = first_amount("tax_total")
    tax_conf = 0.9
    if tax is None:
        parts = []
        for i, ln, mm in _find_label_line(lines, LABELS["tax_part"], r"gstin|vat\s*(?:id|no|nr|reg)|tax\s*(?:id|invoice|no)|ust-?id|\btax\s*number"):
            if re.search(r"sub\s*-?\s*total|total\s*(?:amount|due)|grand", ln, re.I):
                continue
            v = _value_for(lines, i, hint)
            if v is not None:
                parts.append((mm.group(0).lower(), v))
        if parts:
            kinds = {k for k, _ in parts}
            if {"cgst", "sgst"} <= kinds:
                tax = sum((v for k, v in parts if k in ("cgst", "sgst", "utgst")), Decimal(0))
            elif len(parts) == 1:
                tax = parts[0][1]
            else:
                tax, tax_conf = parts[0][1], 0.5
                p.uncertain.append("tax_amount")
                p.notes["tax_amount"] = "Several tax lines found; only the first was used."
    if tax is not None:
        p.tax_amount, p.confidence["tax_amount"] = abs(tax), tax_conf

    disc = None
    for i, ln, mm in _find_label_line(lines, LABELS["discount"], r"total\s*discount\s*%"):
        v = _value_for(lines, i, hint)
        if v is not None:
            disc = v
            break
    if disc is not None:
        p.discount_amount, p.confidence["discount_amount"] = abs(disc), 0.85

    # ---- vendor
    for ln in lines[:15]:
        m = VENDOR_LABEL_RE.match(ln)
        if m:
            p.vendor_name, p.confidence["vendor_name"] = m.group(1).strip()[:200], 0.9
            break
    if not p.vendor_name:
        for ln in lines[:8]:
            if VENDOR_SKIP.match(ln) or len(re.findall(r"[A-Za-zÀ-ÿ]", ln)) < 3:
                continue
            if re.fullmatch(r"[\d\s\-/.,:]+", ln) or "@" in ln or re.search(r"\d{5,}", ln):
                continue
            p.vendor_name, p.confidence["vendor_name"] = ln[:200], 0.7
            p.notes["vendor_name"] = "Taken from the first suitable line of the document; verify."
            break

    # ---- tax id
    m = GSTIN_RE.search(text)
    if m:
        p.tax_id = m.group(0)
    else:
        m = VAT_RE.search(text)
        if m:
            p.tax_id = re.sub(r"\s", "", m.group(1)).upper()

    # ---- line items (single-row layout: description qty unit [tax] total)
    row = re.compile(
        r"^(?P<d>.*?[A-Za-zÀ-ÿ].*?)\s+(?P<q>\d+(?:[.,]\d+)?)\s*(?:x|×)?\s+[\u20b9€£$]?\s*(?P<u>" + NUM + r")\s+(?:(?P<t>" + NUM + r")\s+)?[\u20b9€£$]?\s*(?P<l>" + NUM + r")\s*(?:[A-Z]{3}|[\u20b9€£$])?$")
    for ln in lines:
        if re.search(r"^(?:" + "|".join([LABELS["total_strong"], LABELS["total_plain"], LABELS["subtotal"], LABELS["tax_part"], LABELS["discount"], LABELS["total_due"]]) + r")\b", ln, re.I):
            continue
        m = row.match(ln)
        if not m:
            continue
        item = {
            "description": m["d"].strip()[:300],
            "quantity": parse_amount(m["q"], hint),
            "unit_price": parse_amount(m["u"], hint),
            "tax_amount": parse_amount(m["t"], hint) if m["t"] else None,
            "line_total": parse_amount(m["l"], hint),
        }
        if item["line_total"] is not None:
            p.line_items.append(item)
    if p.line_items:
        p.description = p.line_items[0]["description"]

    # ---- finish
    for k in ("vendor_name", "invoice_date", "currency", "total_amount"):
        if getattr(p, k) in (None, "") and k not in p.uncertain:
            p.uncertain.append(k)
    p.uncertain = list(dict.fromkeys(p.uncertain))
    if default_currency and not p.currency:
        p.notes["currency"] = f"No currency found in the document; organization default is {default_currency}. Please confirm."
    for k in ("subtotal", "tax_amount", "discount_amount", "total_amount"):
        v = getattr(p, k)
        if v is not None and p.currency:
            setattr(p, k, quantize_money(v, p.currency) if v == quantize_money(v, p.currency) else v)
    for it in p.line_items:
        it.setdefault("tax_amount", None)
    return p
