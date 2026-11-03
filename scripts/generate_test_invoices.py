"""Write the synthetic sample documents to ./samples so you can upload them manually.  python scripts/generate_test_invoices.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from tests.fixtures import docs  # noqa: E402

out = ROOT / "samples"
out.mkdir(exist_ok=True)
files = {
    "abc-office-supplies.pdf": docs.invoice_pdf(), "abc-office-supplies-copy.pdf": docs.invoice_pdf(),
    "abc-reprint.pdf": docs.invoice_pdf(footer="Page 1 of 1 - reprinted"), "rechnung-german-eur.pdf": docs.german_invoice_pdf(),
    "ambiguous-date.pdf": docs.ambiguous_date_pdf(), "missing-invoice-number.pdf": docs.missing_number_pdf(),
    "wrong-totals.pdf": docs.mismatched_total_pdf(), "receipt-scan.png": docs.receipt_png(), "scanned-receipt.pdf": docs.scanned_pdf(),
}
for name, data in files.items():
    (out / name).write_bytes(data)
(out / "bank-statement.csv").write_text(docs.BANK_CSV)
print(f"Wrote {len(files) + 1} files to {out}")
