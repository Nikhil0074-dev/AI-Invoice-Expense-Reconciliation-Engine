"""Seed a running server with SYNTHETIC demo data through the public API.

    python scripts/seed_demo_data.py --base-url http://localhost:8000

Creates demo@example.com / DemoPass123 with a realistic mix: clean and messy invoices, a scan, a German invoice,
duplicates, a failed file, bank transactions and a confirmed reconciliation. No real financial data is used.
"""
import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from tests.fixtures import docs  # noqa: E402

EMAIL, PASSWORD = "demo@example.com", "DemoPass123"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    base = ap.parse_args().base_url.rstrip("/") + "/api/v1"
    c = httpx.Client(timeout=60)
    r = c.post(f"{base}/auth/register", json={"email": EMAIL, "password": PASSWORD, "display_name": "Asha Rao",
                                              "organization_name": "Acme Traders Pvt Ltd"})
    if r.status_code == 409:
        r = c.post(f"{base}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    org = c.get(f"{base}/organizations", headers=h).json()[0]
    h["X-Organization-Id"] = org["id"]
    if c.get(f"{base}/documents", headers=h).json()["total"]:
        print("Demo data already present; nothing to do.")
        return

    def up(data, name, mime="application/pdf"):
        r = c.post(f"{base}/documents", headers=h, files={"file": (name, data, mime)})
        r.raise_for_status()
        for _ in range(100):  # processing is asynchronous: poll until the job leaves QUEUED/PROCESSING
            doc = c.get(f"{base}/documents/{r.json()['document_id']}", headers=h).json()
            if doc["processing_status"] not in ("QUEUED", "PROCESSING", "UPLOADED"):
                return doc
            time.sleep(0.3)
        raise SystemExit(f"Timed out waiting for {name}")

    def verify(doc, **patch):
        if patch:
            c.patch(f"{base}/invoices/{doc['invoice_id']}", headers=h, json=patch).raise_for_status()
        c.post(f"{base}/invoices/{doc['invoice_id']}/verify", headers=h, json={"acknowledge_warnings": True}).raise_for_status()

    def inv(vendor, number, date, total, cur="INR", cat=None, items=None):
        sub = f"{total:,.2f}"
        d = docs.invoice_pdf(vendor, number, date, None, cur, items or (("Services", 1, sub, sub),), sub, "", "", sub, gstin="")
        return up(d, f"{vendor.split()[0].lower()}-{number}.pdf")

    # earlier months so the charts have history
    for vendor, number, date, total, cat in [
        ("Zeta Cloud Hosting", "ZC-0817", "17 Aug 2026", 2400, "Software"), ("Pune Print House", "PP-231", "28 Aug 2026", 1850, "Office supplies"),
        ("Zeta Cloud Hosting", "ZC-0917", "17 Sep 2026", 2400, "Software"), ("Metro Travel Desk", "MT-5510", "21 Sep 2026", 7600, "Travel"),
        ("Pune Print House", "PP-244", "30 Sep 2026", 920, "Office supplies"),
    ]:
        verify(inv(vendor, number, date, total), category=cat)

    abc = up(docs.invoice_pdf(), "abc-office-supplies-INV-2026-1042.pdf")
    verify(abc, category="Office supplies")
    sharma = up(docs.missing_number_pdf(), "sharma-electricals.pdf")
    verify(sharma, invoice_number="SE-77", category="Hardware")
    up(docs.invoice_pdf(), "scan_0042_copy.pdf")                                  # exact duplicate (file hash)
    up(docs.invoice_pdf(footer="Page 1 of 1 - reprinted"), "abc-reprint.pdf")     # likely duplicate (identity)
    up(docs.receipt_png(), "chai-point-receipt.png", "image/png")                 # OCR
    up(docs.scanned_pdf(docs.receipt_png(["BLUE LEAF BAKERY", "Receipt No: B-209", "Date: 16 Oct 2026", "Croissant 4 90.00 360.00", "Total INR 360.00"])), "scanned-bakery.pdf")
    up(docs.german_invoice_pdf(), "rechnung-R-2026-88.pdf")                       # German, EUR, European numbers
    up(docs.ambiguous_date_pdf(), "nashik-traders.pdf")                           # ambiguous date
    up(docs.mismatched_total_pdf(), "wrong-totals.pdf")                           # arithmetic mismatch
    up(docs.invoice_pdf()[:5] + b"corrupt" * 30, "corrupt-upload.pdf")            # permanent failure

    csv_text = docs.BANK_CSV + "02/10/2026,POS WRONG TOTALS CO,1500.00,,POS1\n05/09/2026,RENT PAYMENT,18000.00,,RENT9\n"
    r = c.post(f"{base}/transactions/import", headers=h, files={"file": ("hdfc-oct.csv", csv_text.encode(), "text/csv")})
    r.raise_for_status()

    sug = c.get(f"{base}/reconciliation/suggestions", headers=h, params={"invoice_id": abc["invoice_id"]}).json()
    c.post(f"{base}/reconciliation/matches", headers=h, json={"match_id": sug[0]["id"]}).raise_for_status()
    c.get(f"{base}/reconciliation/suggestions", headers=h, params={"invoice_id": sharma["invoice_id"]})  # leave suggestions open
    c.post(f"{base}/exports/csv", headers=h, json={"export_type": "expense"}).raise_for_status()
    print(f"Seeded. Sign in as {EMAIL} / {PASSWORD}")


if __name__ == "__main__":
    main()
