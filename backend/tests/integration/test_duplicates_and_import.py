from tests.conftest import upload_and_verify
from tests.fixtures import docs


def flags(s, status="OPEN"):
    return s.get(f"/duplicates?status={status}").json()


def test_exact_duplicate_file_hash(admin):
    d1 = admin.upload(docs.invoice_pdf(), "original.pdf").json()["document_id"]
    d2 = admin.upload(docs.invoice_pdf(), "renamed-copy.pdf").json()["document_id"]
    fl = flags(admin)
    exact = [f for f in fl if f["detection_method"] == "FILE_HASH"]
    assert len(exact) == 1 and exact[0]["category"] == "EXACT" and exact[0]["document_id"] == d2
    assert "identical" in exact[0]["evidence"] and exact[0]["possible_duplicate_filename"] == "original.pdf"
    assert admin.get(f"/documents/{d2}").json()["processing_status"] == "DUPLICATE_REVIEW"
    assert admin.get(f"/documents/{d1}").json()["processing_status"] == "REVIEW_REQUIRED"  # nothing deleted, nothing blocked
    assert admin.get("/documents").json()["total"] == 2


def test_likely_duplicate_same_identity_different_file(admin):
    admin.upload(docs.invoice_pdf(), "a.pdf")
    admin.upload(docs.invoice_pdf(footer="Page 1 of 1 - reprinted"), "b.pdf")
    fl = flags(admin)
    assert len(fl) == 1 and fl[0]["category"] == "LIKELY" and fl[0]["detection_method"] == "INVOICE_IDENTITY"
    assert "vendor, invoice number" in fl[0]["evidence"] and "file itself differs" in fl[0]["evidence"]


def test_not_duplicates_when_numbers_or_amounts_differ(admin):
    admin.upload(docs.invoice_pdf(), "a.pdf")
    admin.upload(docs.invoice_pdf(number="INV-2026-2000"), "b.pdf")  # same vendor+total, different invoice number
    admin.upload(docs.invoice_pdf(total="5,900.00", discount="0.00"), "c.pdf")  # same number, different total
    assert flags(admin) == []


def test_possible_duplicate_similar_number(admin):
    admin.upload(docs.invoice_pdf(number="INV-2026-1042"), "a.pdf")
    admin.upload(docs.invoice_pdf(number="INV-2026-1O42"), "b.pdf")  # OCR-style O/0 confusion
    fl = flags(admin)
    assert len(fl) == 1 and fl[0]["category"] == "POSSIBLE" and "similar" in fl[0]["evidence"]


def test_duplicate_review_flow_and_verify_gate(admin):
    admin.upload(docs.invoice_pdf(), "a.pdf")
    d2 = admin.upload(docs.invoice_pdf(), "b.pdf").json()["document_id"]
    inv2 = admin.get(f"/documents/{d2}").json()["invoice_id"]
    r = admin.post(f"/invoices/{inv2}/verify", json={"acknowledge_warnings": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_REVIEW_PENDING"
    flag = flags(admin)[0]
    res = admin.post(f"/duplicates/{flag['id']}/review", json={"decision": "dismiss", "note": "Different order, same price"})
    assert res.status_code == 200 and res.json()["review_status"] == "DISMISSED"
    assert admin.get(f"/documents/{d2}").json()["processing_status"] == "REVIEW_REQUIRED"
    assert admin.post(f"/invoices/{inv2}/verify", json={"acknowledge_warnings": True}).status_code == 200
    assert admin.post(f"/duplicates/{flag['id']}/review", json={"decision": "dismiss"}).status_code == 409


def test_confirmed_duplicate_is_archived_not_deleted_and_excluded(admin):
    admin.upload(docs.invoice_pdf(), "a.pdf")
    d2 = admin.upload(docs.invoice_pdf(), "b.pdf").json()["document_id"]
    admin.post(f"/duplicates/{flags(admin)[0]['id']}/review", json={"decision": "confirm_duplicate"})
    assert admin.get(f"/documents/{d2}").json()["processing_status"] == "ARCHIVED"
    assert admin.get(f"/documents/{d2}/preview").status_code == 200  # still preserved
    assert admin.get("/invoices").json()["total"] == 1
    assert admin.get("/dashboard").json()["cards"]["potential_duplicates"] == 0
    log = [x for x in admin.get("/audit-logs?entity_type=duplicate_flag").json() if x["action"] == "duplicate.confirm_duplicate"]
    assert log


def test_correcting_invoice_number_resolves_open_identity_flag(admin):
    admin.upload(docs.invoice_pdf(), "a.pdf")
    d2 = admin.upload(docs.invoice_pdf(footer="reprint"), "b.pdf").json()["document_id"]
    inv2 = admin.get(f"/documents/{d2}").json()["invoice_id"]
    assert len(flags(admin)) == 1
    admin.patch(f"/invoices/{inv2}", json={"invoice_number": "INV-2026-9999"})
    assert flags(admin) == []


BANK = "Date,Narration,Withdrawal,Deposit,Ref No\n13/10/2026,ABC OFFICE,5800.00,,T1\n15/10/2026,SALARY,,50000.00,S1\n"


def test_csv_import_mapping_and_sign_convention(admin):
    prev = admin.post("/transactions/import/preview", files={"file": ("b.csv", BANK.encode(), "text/csv")}).json()
    assert prev["suggested_mapping"]["debit"] == "Withdrawal" and prev["row_count"] == 2
    r = admin.import_csv(BANK).json()
    assert r["imported"] == 2 and r["error_count"] == 0
    items = {t["reference"]: t for t in admin.get("/transactions").json()["items"]}
    assert items["T1"]["amount"].startswith("-5800") and items["S1"]["amount"].startswith("50000")
    assert items["S1"]["status"] == "INFLOW" and items["T1"]["status"] == "UNMATCHED"


def test_csv_split_amounts_reject_both_debit_and_credit(admin):
    csv_text = "Date,Description,Withdrawal,Deposit\n2026-10-01,Ambiguous,100.00,50.00\n"
    result = admin.import_csv(csv_text).json()
    assert result["imported"] == 0 and result["error_count"] == 1
    assert "Both debit and credit" in result["errors"][0]["message"]
    assert admin.get("/transactions").json()["total"] == 0


def test_single_amount_column_sign_conventions(admin):
    csv_text = "Transaction Date,Description,Amount,Currency\n2026-10-01,Vendor A,-100.50,INR\n2026-10-02,Vendor B,200.00,USD\n"
    admin.import_csv(csv_text, sign_convention="negative_is_outflow")
    amounts = sorted(t["amount"][:7] for t in admin.get("/transactions").json()["items"])
    assert amounts == ["-100.50", "200.000"] or amounts[0].startswith("-100.5")
    outflow = [t for t in admin.get("/transactions").json()["items"] if t["status"] != "INFLOW"]
    assert len(outflow) == 1 and outflow[0]["currency"] == "INR"
    admin.import_csv(csv_text.replace("Vendor A", "Vendor C").replace("Vendor B", "Vendor D"), sign_convention="positive_is_outflow")
    out = [t for t in admin.get("/transactions").json()["items"] if t["description"] in ("Vendor C", "Vendor D")]
    by = {t["description"]: t for t in out}
    assert by["Vendor C"]["status"] == "INFLOW" and by["Vendor D"]["amount"].startswith("-200")
    assert admin.import_csv(csv_text, sign_convention="sideways").status_code == 422


def test_repeated_import_creates_no_duplicates_but_identical_rows_in_one_file_are_kept(admin):
    twice = "Date,Description,Amount\n2026-10-01,Coffee,-3.00\n2026-10-01,Coffee,-3.00\n"
    assert admin.import_csv(twice).json()["imported"] == 2  # two genuine identical purchases
    again = admin.import_csv(twice).json()
    assert again["imported"] == 0 and again["skipped_duplicates"] == 2
    assert admin.get("/transactions").json()["total"] == 2
    more = twice + "2026-10-02,Tea,-2.00\n"
    r = admin.import_csv(more).json()
    assert r["imported"] == 1 and r["skipped_duplicates"] == 2


def test_import_errors_dry_run_and_formats(admin):
    bad = "Date,Description,Amount\nnot-a-date,X,-1\n2026-10-01,Y,abc\n2026-10-03,Z,\"1.234,50\"\n"
    r = admin.import_csv(bad, dry_run="true").json()
    assert r["dry_run"] and r["imported"] == 1 and r["error_count"] == 2 and admin.get("/transactions").json()["total"] == 0
    r = admin.import_csv(bad).json()
    assert r["imported"] == 1 and {e["row"] for e in r["errors"]} == {2, 3}
    assert admin.get("/transactions").json()["items"][0]["amount"].startswith("1234.5")  # European number format
    assert admin.import_csv("A,B\n1,2\n").json() if False else admin.import_csv("A,B\n1,2\n").status_code == 422  # mapping required
    semi = "Datum;Beschreibung;Betrag\n12.10.2026;Büro;-1.190,00\n"
    assert admin.import_csv(semi, default_currency="EUR").json()["imported"] == 1
    assert admin.post("/transactions/import", files={"file": ("x.csv", docs.invoice_pdf(), "text/csv")}).status_code == 400
    assert admin.import_csv("").status_code == 400
    assert admin.import_csv(BANK, mapping="[1,2]").status_code == 422
