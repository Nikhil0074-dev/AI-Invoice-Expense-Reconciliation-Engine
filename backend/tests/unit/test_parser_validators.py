from datetime import date
from decimal import Decimal

from app.processors.invoice_parser import parse_invoice_text
from app.processors.validators import validate_invoice

EN = """ABC Office Supplies
TAX INVOICE
Invoice No: INV-2026-1042
Invoice Date: 12 October 2026
Due Date: 11 November 2026
Printer paper 10 500.00 5,000.00
Subtotal ₹5,000.00
GST (18%) ₹900.00
Discount ₹100.00
Grand Total ₹5,800.00
GSTIN: 27ABCDE1234F1Z5
"""


def test_parse_english_invoice():
    p = parse_invoice_text(EN)
    assert (p.vendor_name, p.invoice_number) == ("ABC Office Supplies", "INV-2026-1042")
    assert p.invoice_date == date(2026, 10, 12) and p.due_date == date(2026, 11, 11)
    assert p.currency == "INR"
    assert (p.subtotal, p.tax_amount, p.discount_amount, p.total_amount) == tuple(Decimal(x) for x in ("5000", "900", "100", "5800"))
    assert p.tax_id == "27ABCDE1234F1Z5"
    assert len(p.line_items) == 1 and p.line_items[0]["line_total"] == Decimal("5000.00")


def test_parse_german_invoice_european_numbers():
    p = parse_invoice_text("Muster GmbH\nRechnung Nr. R-2026-88\nRechnungsdatum: 12.10.2026\nZwischensumme 1.000,00 EUR\n"
                           "MwSt 19% 190,00 EUR\nGesamtbetrag 1.190,00 EUR")
    assert p.language == "de" and p.currency == "EUR" and p.invoice_number == "R-2026-88"
    assert p.total_amount == Decimal("1190.00") and p.tax_amount == Decimal("190.00")
    assert p.invoice_date == date(2026, 10, 12)


def test_table_layout_amount_on_next_line():
    p = parse_invoice_text("Vendor Inc\nInvoice Number: A-77\nInvoice Date: 2026-10-01\nTotal\n1,250.00\nUSD")
    assert p.total_amount == Decimal("1250.00")


def test_cgst_sgst_are_summed():
    p = parse_invoice_text("V Ltd\nInvoice No: X-1\nDate: 2026-10-01\nSubtotal 1000.00\nCGST 90.00\nSGST 90.00\nTotal INR 1180.00")
    assert p.tax_amount == Decimal("180.00")


def test_total_does_not_pick_subtotal_or_total_tax():
    p = parse_invoice_text("V Ltd\nInvoice No: X-1\nDate: 2026-10-01\nSubtotal 1000.00\nTotal Tax 180.00\nTotal 1180.00 INR")
    assert p.total_amount == Decimal("1180.00") and p.subtotal == Decimal("1000.00") and p.tax_amount == Decimal("180.00")


def test_ambiguous_date_is_flagged_not_silently_accepted():
    p = parse_invoice_text("V Ltd\nInvoice No: X-1\nInvoice Date: 05/10/2026\nTotal INR 10.00")
    assert "invoice_date" in p.uncertain and p.confidence["invoice_date"] < 0.6


def test_missing_fields_are_marked_uncertain_never_guessed():
    p = parse_invoice_text("just some words without any numbers")
    assert p.total_amount is None and p.currency is None and p.invoice_date is None and p.invoice_number is None
    assert {"currency", "total_amount", "invoice_date"} <= set(p.uncertain)


def test_dollar_sign_flags_currency():
    p = parse_invoice_text("V Inc\nInvoice No: 12\nInvoice Date: 2026-10-01\nTotal $50.00")
    assert p.currency == "USD" and "currency" in p.uncertain


def codes(w):
    return {x["code"] for x in w}


BASE = dict(vendor_name="V", invoice_number="1", invoice_date=date(2026, 10, 1), due_date=None, currency="INR",
            subtotal=Decimal("5000"), tax_amount=Decimal("900"), discount_amount=Decimal("100"), total_amount=Decimal("5800"))


def test_validator_accepts_consistent_totals():
    assert not {"TOTAL_MISMATCH"} & codes(validate_invoice(BASE, []))


def test_validator_flags_total_mismatch_without_fixing_it():
    w = validate_invoice({**BASE, "total_amount": Decimal("6000")}, [])
    assert "TOTAL_MISMATCH" in codes(w)


def test_validator_accepts_tax_inclusive_and_no_discount_formulas():
    assert "TOTAL_MISMATCH" not in codes(validate_invoice({**BASE, "discount_amount": None, "total_amount": Decimal("5900")}, []))
    assert "TOTAL_MISMATCH" not in codes(validate_invoice({**BASE, "tax_amount": Decimal("900"), "total_amount": Decimal("5000")}, []))


def test_validator_missing_required_are_errors():
    w = validate_invoice({"vendor_name": None, "currency": None, "total_amount": None, "invoice_date": None}, [])
    assert {"MISSING_CURRENCY", "MISSING_TOTAL_AMOUNT", "MISSING_INVOICE_DATE", "MISSING_VENDOR_NAME"} <= codes(w)
    assert all(x["severity"] == "error" for x in w if x["code"].startswith("MISSING_") and x["code"] != "MISSING_INVOICE_NUMBER")


def test_validator_line_items():
    items = [{"quantity": Decimal(10), "unit_price": Decimal(500), "tax_amount": None, "line_total": Decimal(4000)}]
    w = codes(validate_invoice(BASE, items))
    assert "LINE_ITEM_ARITHMETIC" in w and "LINE_ITEMS_SUM_MISMATCH" in w
    ok = [{"quantity": Decimal(10), "unit_price": Decimal(500), "tax_amount": None, "line_total": Decimal(5000)}]
    assert not {"LINE_ITEM_ARITHMETIC", "LINE_ITEMS_SUM_MISMATCH"} & codes(validate_invoice(BASE, ok))


def test_validator_precision_negative_and_due_date():
    w = codes(validate_invoice({**BASE, "total_amount": Decimal("5800.123"), "due_date": date(2026, 9, 1), "tax_amount": Decimal("-1")}, []))
    assert {"EXCESS_PRECISION", "DUE_BEFORE_INVOICE", "NEGATIVE_AMOUNT"} <= w
