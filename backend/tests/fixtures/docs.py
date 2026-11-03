"""Synthetic invoice generators (no real financial data). Used by tests, seed script and screenshots."""
import io

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def _pdf(lines: list[str], footer: str = "") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    y = 800
    for i, line in enumerate(lines):
        c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 16 if i == 0 else 11)
        c.drawString(50, y, line)
        y -= 22 if i == 0 else 18
    if footer:
        c.setFont("Helvetica", 8)
        c.drawString(50, 40, footer)
    c.showPage()
    c.save()
    return buf.getvalue()


def invoice_pdf(vendor="ABC Office Supplies", number="INV-2026-1042", date="12 October 2026", due="11 November 2026",
                cur="INR", items=(("Printer paper", 10, "500.00", "5,000.00"),), subtotal="5,000.00", tax="900.00",
                discount="100.00", total="5,800.00", tax_label="GST (18%)", footer="", gstin="27ABCDE1234F1Z5") -> bytes:
    lines = [vendor, f"GSTIN: {gstin}", "TAX INVOICE", f"Invoice No: {number}", f"Invoice Date: {date}"]
    if due:
        lines.append(f"Due Date: {due}")
    lines.append("Description Qty Unit Price Amount")
    for d, q, u, t in items:
        lines.append(f"{d} {q} {u} {t}")
    lines.append(f"Subtotal {cur} {subtotal}")
    if tax:
        lines.append(f"{tax_label} {cur} {tax}")
    if discount:
        lines.append(f"Discount {cur} {discount}")
    lines.append(f"Grand Total {cur} {total}")
    return _pdf(lines, footer)


def german_invoice_pdf() -> bytes:
    return _pdf(["Muster Büro GmbH", "Rechnung", "Rechnung Nr. R-2026-88", "Rechnungsdatum: 12.10.2026",
                 "Fälligkeitsdatum: 11.11.2026", "Bürostuhl 2 500,00 1.000,00",
                 "Zwischensumme 1.000,00 EUR", "MwSt 19% 190,00 EUR", "Gesamtbetrag 1.190,00 EUR"])


def ambiguous_date_pdf() -> bytes:
    return invoice_pdf("Nashik Traders", "NT-5521", "05/10/2026", None, "INR", (("Cable", 2, "250.00", "500.00"),),
                       "500.00", "", "", "500.00")


def missing_number_pdf() -> bytes:
    return _pdf(["Sharma Electricals", "Bill", "Date: 03 Oct 2026", "Total INR 10,000.00"])


def mismatched_total_pdf() -> bytes:
    return invoice_pdf("Wrong Totals Co", "WT-1", "01 Oct 2026", None, "INR", (("Item", 1, "1,000.00", "1,000.00"),),
                       "1,000.00", "180.00", "", "1,500.00")


def receipt_png(lines: list[str] | None = None, size: int = 34) -> bytes:
    lines = lines or ["CHAI POINT CAFE", "Receipt No: R-4471", "Date: 14 Oct 2026", "Masala Chai 3 50.00 150.00",
                      "Sandwich 2 150.00 300.00", "Subtotal INR 450.00", "Total INR 450.00"]
    font = ImageFont.load_default(size=size)
    img = Image.new("RGB", (1100, 90 + len(lines) * (size + 22)), "white")
    d = ImageDraw.Draw(img)
    y = 40
    for ln in lines:
        d.text((50, y), ln, fill=(20, 20, 20), font=font)
        y += size + 22
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def scanned_pdf(png: bytes | None = None) -> bytes:
    """Image-only PDF (no text layer) -> must go through OCR."""
    from reportlab.lib.utils import ImageReader
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.drawImage(ImageReader(io.BytesIO(png or receipt_png())), 30, 400, width=530, preserveAspectRatio=True, mask="auto")
    c.showPage()
    c.save()
    return buf.getvalue()


def malicious_pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj<< /Type /Catalog /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>endobj\ntrailer<<>>\n%%EOF"


BANK_CSV = """Date,Narration,Withdrawal,Deposit,Ref No
13/10/2026,UPI/ABC OFFICE SUPPLIES/TXN893021,5800.00,,TXN-893021
09/10/2026,NEFT SHARMA ELECTRICALS,6000.00,,UTR1001
12/10/2026,NEFT SHARMA ELECTRICALS,4000.00,,UTR1002
14/10/2026,POS CHAI POINT CAFE,450.00,,POS7781
15/10/2026,SALARY CREDIT,,50000.00,SAL1
20/10/2026,AMAZON WEB SERVICES,1234.56,,AWS9
"""
