import csv
import io

from tests.conftest import add_member, upload_and_verify
from tests.fixtures import docs

SPLIT_BANK = """Date,Narration,Withdrawal,Ref No
09/10/2026,NEFT SHARMA ELECTRICALS,6000.00,UTR1
12/10/2026,NEFT SHARMA ELECTRICALS,4000.00,UTR2
13/10/2026,UPI/ABC OFFICE SUPPLIES/TXN893021,5800.00,TXN-893021
20/10/2026,AMAZON WEB SERVICES,1234.56,AWS9
"""


def tx_by_ref(s):
    return {t["reference"]: t for t in s.get("/transactions").json()["items"]}


def test_example_a_suggest_confirm_and_statuses(admin):
    admin.import_csv(SPLIT_BANK)
    inv_id, doc = upload_and_verify(admin, docs.invoice_pdf())
    sug = admin.get(f"/reconciliation/suggestions?invoice_id={inv_id}").json()
    assert sug[0]["match_status"] == "SUGGESTED" and sug[0]["match_score"] >= 0.8
    assert sug[0]["transactions"][0]["reference"] == "TXN-893021"
    assert "amount matches" in sug[0]["match_explanation"] and "vendor" in sug[0]["match_explanation"]
    assert admin.get(f"/invoices/{inv_id}").json()["reconciliation_status"] == "SUGGESTED"
    r = admin.post("/reconciliation/matches", json={"match_id": sug[0]["id"]})
    assert r.status_code == 201 and r.json()["match_status"] == "CONFIRMED"
    inv = admin.get(f"/invoices/{inv_id}").json()
    assert inv["reconciliation_status"] == "CONFIRMED" and inv["document_status"] == "RECONCILED"
    t = tx_by_ref(admin)["TXN-893021"]
    assert t["status"] == "RECONCILED" and t["allocated"].startswith("5800")
    assert admin.post("/reconciliation/matches", json={"match_id": sug[0]["id"]}).status_code == 409


def test_suggestions_require_verified_invoice(admin):
    admin.import_csv(SPLIT_BANK)
    inv = admin.get(f"/documents/{admin.upload(docs.invoice_pdf()).json()['document_id']}").json()["invoice_id"]
    r = admin.get(f"/reconciliation/suggestions?invoice_id={inv}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVOICE_NOT_VERIFIED"


def test_example_c_split_payment(admin):
    admin.import_csv(SPLIT_BANK)
    inv_id, _ = upload_and_verify(admin, docs._pdf(["Sharma Electricals", "Invoice No: SE-77", "Invoice Date: 08 Oct 2026",
                                                    "Total INR 10,000.00"]), "sharma.pdf")
    sug = admin.get(f"/reconciliation/suggestions?invoice_id={inv_id}").json()
    split = next(m for m in sug if m["kind"] == "SPLIT")
    assert len(split["transaction_ids"]) == 2 and split["match_status"] == "NEEDS_REVIEW"
    assert admin.post("/reconciliation/matches", json={"match_id": split["id"]}).status_code == 201
    inv = admin.get(f"/invoices/{inv_id}").json()
    assert inv["reconciliation_status"] == "CONFIRMED" and inv["allocated_amount"].startswith("10000")
    refs = tx_by_ref(admin)
    assert refs["UTR1"]["status"] == refs["UTR2"]["status"] == "RECONCILED"


def test_partial_payment_then_second_payment(admin):
    admin.import_csv(SPLIT_BANK)
    inv_id, _ = upload_and_verify(admin, docs._pdf(["Sharma Electricals", "Invoice No: SE-77", "Invoice Date: 08 Oct 2026",
                                                    "Total INR 10,000.00"]), "sharma.pdf")
    refs = tx_by_ref(admin)
    r = admin.post("/reconciliation/matches", json={"invoice_id": inv_id, "allocations": [{"transaction_id": refs["UTR1"]["id"], "amount": "6000"}]})
    assert r.status_code == 201 and r.json()["match_status"] == "PARTIALLY_RECONCILED"
    inv = admin.get(f"/invoices/{inv_id}").json()
    assert inv["reconciliation_status"] == "PARTIALLY_RECONCILED" and inv["document_status"] == "READY_FOR_RECONCILIATION"
    r = admin.post("/reconciliation/matches", json={"invoice_id": inv_id, "allocations": [{"transaction_id": refs["UTR2"]["id"], "amount": "4000"}]})
    assert r.status_code == 201
    assert admin.get(f"/invoices/{inv_id}").json()["reconciliation_status"] == "CONFIRMED"


def test_over_allocation_and_currency_rules(admin):
    admin.import_csv(SPLIT_BANK)
    admin.import_csv("Date,Description,Amount,Currency\n2026-10-13,ABC OFFICE USD,-5800.00,USD\n2026-10-14,Refund,100.00,INR\n")
    inv_id, _ = upload_and_verify(admin, docs.invoice_pdf())
    refs = tx_by_ref(admin)
    aws, usd = refs["AWS9"], next(t for t in admin.get("/transactions").json()["items"] if t["currency"] == "USD")
    refund = next(t for t in admin.get("/transactions").json()["items"] if t["description"] == "Refund")
    pay = lambda tid, amt: admin.post("/reconciliation/matches", json={"invoice_id": inv_id, "allocations": [{"transaction_id": tid, "amount": amt}]})
    assert pay(aws["id"], "2000").json()["error"]["code"] == "OVER_ALLOCATION"        # more than the transaction holds
    assert pay(aws["id"], "1.001").json()["error"]["code"] == "INVALID_ALLOCATION" # fractional minor currency unit
    assert pay(refs["TXN-893021"]["id"], "6000").json()["error"]["code"] == "OVER_ALLOCATION"  # more than the invoice total
    assert pay(usd["id"], "5800").json()["error"]["code"] == "CURRENCY_MISMATCH"
    assert pay(refund["id"], "50").json()["error"]["code"] == "NOT_AN_OUTFLOW"
    assert pay(aws["id"], "0").status_code == 422 and pay(aws["id"], "-5").status_code == 422
    assert admin.post("/reconciliation/matches", json={"invoice_id": inv_id, "allocations": [
        {"transaction_id": aws["id"], "amount": "1"}, {"transaction_id": aws["id"], "amount": "1"}]}).status_code == 422
    assert admin.get(f"/invoices/{inv_id}").json()["allocated_amount"].startswith("0")  # nothing leaked through
    # a transaction cannot be double spent across invoices
    assert pay(refs["TXN-893021"]["id"], "5800").status_code == 201
    inv2, _ = upload_and_verify(admin, docs.invoice_pdf(number="INV-OTHER", date="14 October 2026"), "other.pdf")
    r = admin.post("/reconciliation/matches", json={"invoice_id": inv2, "allocations": [{"transaction_id": refs["TXN-893021"]["id"], "amount": "5800"}]})
    assert r.json()["error"]["code"] == "OVER_ALLOCATION"


def test_transaction_status_filter_and_database_pagination(admin):
    admin.import_csv("Date,Description,Amount\n2026-10-01,One,-1.00\n2026-10-02,Two,-2.00\n2026-10-03,Salary,10.00\n")
    page = admin.get("/transactions?page=1&page_size=1")
    assert page.status_code == 200 and page.json()["total"] == 3 and len(page.json()["items"]) == 1
    inflows = admin.get("/transactions?status=INFLOW&page_size=1")
    assert inflows.json()["total"] == 1 and inflows.json()["items"][0]["description"] == "Salary"
    assert admin.get("/transactions?status=UNMATCHED&page_size=1").json()["total"] == 2


def test_currency_mismatch_suggestion_warns(admin):
    admin.import_csv("Date,Description,Amount,Currency\n2026-10-13,ABC OFFICE SUPPLIES,-5800.00,USD\n")
    inv_id, _ = upload_and_verify(admin, docs.invoice_pdf())
    sug = admin.get(f"/reconciliation/suggestions?invoice_id={inv_id}").json()
    assert sug and sug[0]["match_status"] == "NEEDS_REVIEW" and "currencies differ" in sug[0]["match_explanation"]
    assert admin.post("/reconciliation/matches", json={"match_id": sug[0]["id"]}).status_code in (409, 422)


def test_reject_unlink_and_no_resuggest(admin):
    admin.import_csv(SPLIT_BANK)
    inv_id, _ = upload_and_verify(admin, docs.invoice_pdf())
    sug = admin.get(f"/reconciliation/suggestions?invoice_id={inv_id}").json()[0]
    assert admin.post(f"/reconciliation/matches/{sug['id']}/reject").json()["match_status"] == "REJECTED"
    assert admin.get(f"/reconciliation/suggestions?invoice_id={inv_id}").json() == []  # rejected pair is not suggested again
    assert admin.get(f"/invoices/{inv_id}").json()["reconciliation_status"] == "UNMATCHED"
    tid = tx_by_ref(admin)["TXN-893021"]["id"]
    m = admin.post("/reconciliation/matches", json={"invoice_id": inv_id, "allocations": [{"transaction_id": tid, "amount": "5800"}]}).json()
    assert admin.post(f"/reconciliation/matches/{m['id']}/reject").status_code == 409
    assert admin.patch(f"/reconciliation/matches/{m['id']}", json={"action": "unlink"}).json()["match_status"] == "REJECTED"
    inv = admin.get(f"/invoices/{inv_id}").json()
    assert inv["reconciliation_status"] == "UNMATCHED" and inv["document_status"] == "READY_FOR_RECONCILIATION"
    assert tx_by_ref(admin)["TXN-893021"]["status"] == "UNMATCHED"
    actions = [x["action"] for x in admin.get("/audit-logs?entity_type=reconciliation_match").json()]
    assert {"match.manual", "match.unlink", "match.reject"} <= set(actions)


def test_reconciled_invoice_is_protected(admin):
    admin.import_csv(SPLIT_BANK)
    inv_id, doc = upload_and_verify(admin, docs.invoice_pdf())
    tid = tx_by_ref(admin)["TXN-893021"]["id"]
    admin.post("/reconciliation/matches", json={"invoice_id": inv_id, "allocations": [{"transaction_id": tid, "amount": "5800"}]})
    assert admin.patch(f"/invoices/{inv_id}", json={"total_amount": "1"}).json()["error"]["code"] == "INVOICE_RECONCILED"
    assert admin.patch(f"/invoices/{inv_id}", json={"category": "Office"}).status_code == 200
    assert admin.delete(f"/documents/{doc['id']}").status_code == 409
    assert admin.post(f"/documents/{doc['id']}/process").status_code == 409


def test_permissions_on_reconciliation(client, admin):
    viewer = add_member(client, admin, "v@acme.example.com", "VIEWER")
    admin.import_csv(SPLIT_BANK)
    inv_id, _ = upload_and_verify(admin, docs.invoice_pdf())
    assert viewer.get(f"/reconciliation/suggestions?invoice_id={inv_id}").status_code == 403
    sug = admin.get(f"/reconciliation/suggestions?invoice_id={inv_id}").json()
    assert viewer.get(f"/reconciliation/suggestions?invoice_id={inv_id}&refresh=false").status_code == 200
    assert viewer.post("/reconciliation/matches", json={"match_id": sug[0]["id"]}).status_code == 403


def read_csv(s, url):
    return list(csv.reader(io.StringIO(s.c.get(url, headers=s.h).content.decode("utf-8-sig"))))


def test_exports_content_validation_and_audit(admin):
    admin.import_csv(SPLIT_BANK)
    inv_id, _ = upload_and_verify(admin, docs.invoice_pdf())
    upload_and_verify(admin, docs.invoice_pdf("=HYPERLINK(\"http://evil\")", "X-1", "05 Oct 2026", None, "INR", (("Item", 1, "100.00", "100.00"),), "100.00", "", "", "100.00"), "evil.pdf")
    admin.upload(docs.invoice_pdf("Unverified Co", "U-1", "06 Oct 2026"), "unverified.pdf")
    tid = tx_by_ref(admin)["TXN-893021"]["id"]
    admin.post("/reconciliation/matches", json={"invoice_id": inv_id, "allocations": [{"transaction_id": tid, "amount": "5800"}]})
    exp = admin.post("/exports/csv", json={"export_type": "invoice_register"})
    assert exp.status_code == 201 and exp.json()["row_count"] == 2  # only verified invoices
    rows = read_csv(admin, exp.json()["download_url"])
    assert rows[0][:5] == ["vendor_name", "invoice_number", "invoice_date", "due_date", "currency"]
    abc = next(r for r in rows if r[0] == "ABC Office Supplies")
    assert abc[1:3] == ["INV-2026-1042", "2026-10-12"] and "5800.0000" in abc or "5800.00" in abc
    assert abc[rows[0].index("reconciliation_status")] == "CONFIRMED"
    assert any(r[0].startswith("'=HYPERLINK") for r in rows)  # CSV injection neutralised
    assert not any("Unverified" in c for r in rows for c in r)
    # filters
    assert admin.post("/exports/csv", json={"export_type": "expense", "date_from": "2026-10-10", "date_to": "2026-10-31"}).json()["row_count"] == 1
    # custom column mapping / template
    custom = admin.post("/exports/csv", json={"export_type": "expense", "columns": [{"source": "vendor_name", "header": "Supplier"},
                                                                                  {"source": "total_amount", "header": "Gross"}]}).json()
    assert read_csv(admin, custom["download_url"])[0] == ["Supplier", "Gross"]
    assert admin.post("/exports/csv", json={"export_type": "expense", "columns": [{"source": "password_hash", "header": "x"}]}).status_code == 422
    assert admin.post("/exports/csv", json={"export_type": "nope"}).status_code == 422
    assert admin.post("/exports/csv", json={"export_type": "expense", "template": "simple_ledger"}).status_code == 201
    # other export types
    br = read_csv(admin, admin.post("/exports/csv", json={"export_type": "bank_reconciliation"}).json()["download_url"])
    assert len(br) == 2 and br[1][br[0].index("allocated_amount")].startswith("5800")
    li = admin.post("/exports/csv", json={"export_type": "line_items"}).json()
    assert li["row_count"] >= 1
    um = read_csv(admin, admin.post("/exports/csv", json={"export_type": "unmatched_transactions"}).json()["download_url"])
    assert len(um) == 4  # header + 3 outflows still unallocated
    assert admin.post("/exports/csv", json={"export_type": "duplicate_review"}).status_code == 201
    audit = [x for x in admin.get("/audit-logs?entity_type=export").json()]
    assert audit and audit[0]["after_state"]["sha256"]
    assert len(admin.get("/exports").json()) >= 7


def test_export_validation_blocks_incomplete_records(admin):
    inv_id, _ = upload_and_verify(admin, docs.invoice_pdf())
    from app.db import session as dbs
    from app.models import BankTransaction, Invoice
    db = dbs.SessionLocal()
    db.get(Invoice, inv_id).total_amount = None  # simulate corrupt data
    db.commit()
    db.close()
    r = admin.post("/exports/csv", json={"export_type": "expense"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "EXPORT_VALIDATION_FAILED" and r.json()["error"]["details"]["records"]


def test_dashboard_numbers(admin):
    admin.import_csv(SPLIT_BANK)
    inv_id, _ = upload_and_verify(admin, docs.invoice_pdf())
    admin.patch(f"/invoices/{inv_id}", json={"category": "Office"})
    admin.upload(docs.invoice_pdf("Pending Co", "P-1", "06 Oct 2026"), "p.pdf")
    admin.upload(docs.invoice_pdf(), "dup.pdf")  # exact duplicate of the first file
    tid = tx_by_ref(admin)["TXN-893021"]["id"]
    admin.post("/reconciliation/matches", json={"invoice_id": inv_id, "allocations": [{"transaction_id": tid, "amount": "5800"}]})
    d = admin.get("/dashboard").json()
    c = d["cards"]
    assert c["total_invoices"] == 3 and float(c["total_expenses"]) == 5800 and float(c["reconciled_expenses"]) == 5800
    assert c["awaiting_review"] == 2 and c["unmatched_transactions"] == 3 and c["potential_duplicates"] >= 1
    assert d["monthly_expenses"] == [{"month": "2026-10", "total": 5800.0}]
    assert d["spend_by_category"][0] == {"category": "Office", "total": 5800.0}
    assert d["spend_by_vendor"][0]["vendor"] == "ABC Office Supplies"
    assert admin.get("/dashboard?date_from=2026-11-01").json()["cards"]["total_expenses"].startswith("0")


def test_end_to_end_acceptance_workflow(client, admin):
    """Upload -> review -> import -> suggestions -> confirm -> duplicate -> export (acceptance criteria)."""
    up = admin.upload(docs.invoice_pdf(), "abc.pdf")
    doc = admin.get(f"/documents/{up.json()['document_id']}").json()
    assert doc["processing_status"] == "REVIEW_REQUIRED"
    inv = admin.get(f"/invoices/{doc['invoice_id']}").json()
    assert inv["total_amount"].startswith("5800") and not [w for w in inv["warnings"] if w["code"] == "TOTAL_MISMATCH"]
    assert admin.post(f"/invoices/{inv['id']}/verify", json={"acknowledge_warnings": True}).status_code == 200
    assert admin.import_csv(docs.BANK_CSV).json()["imported"] == 6
    sug = admin.get(f"/reconciliation/suggestions?invoice_id={inv['id']}").json()
    assert sug[0]["match_score"] >= 0.8 and sug[0]["match_explanation"].startswith("Suggested because")
    assert admin.post("/reconciliation/matches", json={"match_id": sug[0]["id"]}).json()["match_status"] == "CONFIRMED"
    admin.upload(docs.invoice_pdf(), "abc-again.pdf")
    assert any(f["category"] == "EXACT" for f in admin.get("/duplicates").json())
    exp = admin.post("/exports/csv", json={"export_type": "expense"}).json()
    rows = read_csv(admin, exp["download_url"])
    assert rows[1][0] == "ABC Office Supplies" and rows[1][-1] == "CONFIRMED" and exp["row_count"] == 1
