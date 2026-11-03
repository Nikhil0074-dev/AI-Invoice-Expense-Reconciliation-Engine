"""Arithmetic / consistency checks. Warnings are returned, never silently "fixed"."""
from decimal import Decimal

from app.processors.normalize import currency_decimals

TOL = Decimal("0.02")
REQUIRED = ("vendor_name", "invoice_date", "currency", "total_amount")


def _w(code: str, field: str, message: str, severity: str = "warning") -> dict:
    return {"code": code, "field": field, "message": message, "severity": severity}


def _close(a: Decimal, b: Decimal, tol: Decimal = TOL) -> bool:
    return abs(a - b) <= tol


def validate_invoice(inv: dict, line_items: list[dict], uncertain: list[str] | None = None) -> list[dict]:
    """`inv` has Decimal/date/str values; returns list of warning dicts (severity: error|warning|info)."""
    out: list[dict] = []
    uncertain = uncertain or []
    labels = {"vendor_name": "Vendor name", "invoice_date": "Invoice date", "currency": "Currency", "total_amount": "Total amount"}
    for f in REQUIRED:
        if inv.get(f) in (None, ""):
            out.append(_w(f"MISSING_{f.upper()}", f, f"{labels[f]} is missing.", "error"))
    if not inv.get("invoice_number"):
        out.append(_w("MISSING_INVOICE_NUMBER", "invoice_number", "Invoice number is missing (allowed, but weakens duplicate detection and matching).", "info"))
    for f in ("invoice_date", "currency", "vendor_name", "invoice_number", "due_date", "total_amount", "tax_amount"):
        if f in uncertain and inv.get(f) not in (None, ""):
            out.append(_w(f"UNCERTAIN_{f.upper()}", f, f"{f.replace('_', ' ').capitalize()} is uncertain; please verify against the document."))

    cur = inv.get("currency")
    dec = currency_decimals(cur)
    for f in ("subtotal", "tax_amount", "discount_amount", "total_amount"):
        v = inv.get(f)
        if v is None:
            continue
        if v < 0:
            out.append(_w("NEGATIVE_AMOUNT", f, f"{f.replace('_', ' ').capitalize()} is negative."))
        if cur and -Decimal(v).normalize().as_tuple().exponent > dec:
            out.append(_w("EXCESS_PRECISION", f, f"{cur} amounts normally have {dec} decimal places."))
    if inv.get("invoice_date") and inv.get("due_date") and inv["due_date"] < inv["invoice_date"]:
        out.append(_w("DUE_BEFORE_INVOICE", "due_date", "Due date is before the invoice date."))

    s, t, d, total = inv.get("subtotal"), inv.get("tax_amount"), inv.get("discount_amount"), inv.get("total_amount")
    if s is not None and total is not None:
        t0, d0 = t or Decimal(0), d or Decimal(0)
        variants = {"subtotal + tax - discount": s + t0 - d0, "subtotal + tax": s + t0,
                    "subtotal - discount": s - d0, "subtotal (tax included)": s}
        if not any(_close(v, total) for v in variants.values()):
            out.append(_w("TOTAL_MISMATCH", "total_amount",
                          "Total {} does not match any common combination of subtotal {}, tax {} and discount {} ({}). "
                          "Verify against the printed document.".format(
                              total, s, t if t is not None else "n/a", d if d is not None else "n/a",
                              ", ".join(f"{k} = {v}" for k, v in variants.items()))))

    items = [li for li in line_items if li.get("line_total") is not None]
    for n, li in enumerate(items, 1):
        q, u, lt = li.get("quantity"), li.get("unit_price"), li["line_total"]
        if q is not None and u is not None and not _close(q * u, lt, Decimal("0.05")):
            # tolerate tax-inclusive line totals
            if not (li.get("tax_amount") is not None and _close(q * u + li["tax_amount"], lt, Decimal("0.05"))):
                out.append(_w("LINE_ITEM_ARITHMETIC", "line_items", f"Line {n}: quantity x unit price ({q * u}) differs from line total ({lt})."))
    if items:
        line_sum = sum((li["line_total"] for li in items), Decimal(0))
        targets = [x for x in (s, total) if x is not None]
        if targets:
            cands = list(targets)
            if s is not None and t:
                cands.append(s + t)
            if total is not None and t:
                cands.append(total - t)
            if total is not None and t is not None and d is not None:
                cands.append(total - t + d)
            if not any(_close(line_sum, c) for c in cands):
                out.append(_w("LINE_ITEMS_SUM_MISMATCH", "line_items",
                              f"Line items add up to {line_sum}, which does not match the subtotal/total on the invoice."))
    return out


def blocking_errors(warnings: list[dict]) -> list[dict]:
    return [w for w in warnings if w["severity"] == "error"]
