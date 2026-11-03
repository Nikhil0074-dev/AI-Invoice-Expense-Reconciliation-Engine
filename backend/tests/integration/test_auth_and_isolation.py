from tests.conftest import add_member, make_user
from tests.fixtures import docs


def test_register_login_me_and_duplicate_email(client):
    r = client.post("/api/v1/auth/register", json={"email": "A@x.example.com", "password": "longenough1", "display_name": "A"})
    assert r.status_code == 201
    assert client.post("/api/v1/auth/register", json={"email": "a@x.example.com", "password": "longenough1", "display_name": "A"}).status_code == 409
    tok = client.post("/api/v1/auth/login", json={"email": "a@x.example.com", "password": "longenough1"}).json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200 and me.json()["email"] == "a@x.example.com"
    bad = client.post("/api/v1/auth/login", json={"email": "a@x.example.com", "password": "wrong-password"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_validation_errors_use_consistent_shape(client):
    r = client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "x", "display_name": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_password_reset_flow(client):
    client.post("/api/v1/auth/register", json={"email": "r@x.example.com", "password": "oldpassword1", "display_name": "R"})
    tok = client.post("/api/v1/auth/password-reset/request", json={"email": "r@x.example.com"}).json()["dev_reset_token"]
    assert client.post("/api/v1/auth/password-reset/confirm", json={"token": tok, "new_password": "newpassword1"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "r@x.example.com", "password": "newpassword1"}).status_code == 200
    unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "nobody@x.example.com"}).json()
    assert "dev_reset_token" not in unknown  # no account enumeration
    # an access token must not work as a reset token
    access = client.post("/api/v1/auth/login", json={"email": "r@x.example.com", "password": "newpassword1"}).json()["access_token"]
    assert client.post("/api/v1/auth/password-reset/confirm", json={"token": access, "new_password": "another-pass1"}).status_code == 401


def test_unauthenticated_access_is_rejected(client):
    for path in ("/documents", "/invoices", "/transactions", "/dashboard", "/exports"):
        assert client.get("/api/v1" + path).status_code == 401


def test_organization_isolation_on_every_resource(client):
    a = make_user(client, "a@a.example.com", "Org A")
    b = make_user(client, "b@b.example.com", "Org B")
    doc_id = a.upload(docs.invoice_pdf()).json()["document_id"]
    inv_id = a.get(f"/documents/{doc_id}").json()["invoice_id"]
    a.import_csv(docs.BANK_CSV)
    tx_id = a.get("/transactions").json()["items"][0]["id"]
    # B cannot see or touch anything of A
    assert b.get("/documents").json()["total"] == 0 and b.get("/invoices").json()["total"] == 0
    assert b.get("/transactions").json()["total"] == 0
    for url in (f"/documents/{doc_id}", f"/documents/{doc_id}/preview", f"/documents/{doc_id}/download", f"/invoices/{inv_id}"):
        assert b.get(url).status_code == 404, url
    assert b.patch(f"/invoices/{inv_id}", json={"vendor_name": "hijack"}).status_code == 404
    assert b.post(f"/invoices/{inv_id}/verify", json={"acknowledge_warnings": True}).status_code == 404
    assert b.delete(f"/documents/{doc_id}").status_code == 404
    assert b.post(f"/documents/{doc_id}/process").status_code == 404
    # B using A's organization id header is forbidden
    forged = dict(b.h, **{"X-Organization-Id": a.org_id})
    assert client.get("/api/v1/documents", headers=forged).status_code == 403
    # B cannot link A's transaction to B's own invoice
    inv_b, _ = __import__("tests.conftest", fromlist=["x"]).upload_and_verify(b, docs.invoice_pdf(), "b.pdf")
    r = b.post("/reconciliation/matches", json={"invoice_id": inv_b, "allocations": [{"transaction_id": tx_id, "amount": "100"}]})
    assert r.status_code == 404
    # B's exports never contain A's data
    exp = b.post("/exports/csv", json={"export_type": "invoice_register"}).json()
    body = b.c.get(exp["download_url"], headers=b.h).text
    assert "ABC Office" in body and body.count("\n") == 2  # header + B's own single row
    assert a.get(exp["download_url"].replace("/api/v1", "")).status_code == 404


def test_role_permissions(client, admin):
    admin.upload(docs.invoice_pdf())
    viewer = add_member(client, admin, "viewer@acme.example.com", "VIEWER")
    contributor = add_member(client, admin, "contrib@acme.example.com", "CONTRIBUTOR")
    accountant = add_member(client, admin, "acct@acme.example.com", "ACCOUNTANT")
    assert viewer.get("/documents").status_code == 200
    assert viewer.upload(docs.invoice_pdf()).status_code == 403
    assert viewer.post("/exports/csv", json={"export_type": "expense"}).status_code == 403
    assert contributor.upload(docs.invoice_pdf(number="INV-2")).status_code == 201
    inv_id = contributor.get("/invoices").json()["items"][0]["id"]
    assert contributor.patch(f"/invoices/{inv_id}", json={"category": "Office"}).status_code == 200
    assert contributor.post(f"/invoices/{inv_id}/verify", json={"acknowledge_warnings": True}).status_code == 403
    assert contributor.import_csv(docs.BANK_CSV).status_code == 403
    assert contributor.patch(f"/organizations/{admin.org_id}", json={"name": "x"}).status_code == 403
    assert accountant.import_csv(docs.BANK_CSV).status_code == 200
    assert accountant.post(f"/organizations/{admin.org_id}/members", json={"email": "z@z.example.com", "role": "VIEWER"}).status_code == 403
    assert accountant.post("/exports/csv", json={"export_type": "expense"}).status_code == 201


def test_member_management_rules(client, admin):
    add_member(client, admin, "m@acme.example.com", "VIEWER")
    members = admin.get(f"/organizations/{admin.org_id}/members").json()
    assert len(members) == 2
    me = next(m for m in members if m["email"] == "admin@acme.example.com")
    assert admin.delete(f"/organizations/{admin.org_id}/members/{me['id']}").status_code == 409  # last admin
    assert admin.patch(f"/organizations/{admin.org_id}/members/{me['id']}", json={"role": "VIEWER"}).status_code == 409
    assert admin.post(f"/organizations/{admin.org_id}/members", json={"email": "m@acme.example.com", "role": "VIEWER"}).status_code == 409
    assert admin.post(f"/organizations/{admin.org_id}/members", json={"email": "ghost@x.example.com", "role": "VIEWER"}).status_code == 404


def test_settings_validation(admin):
    r = admin.patch(f"/organizations/{admin.org_id}", json={"match_review_threshold": 0.9, "match_high_threshold": 0.8})
    assert r.status_code == 422
    r = admin.patch(f"/organizations/{admin.org_id}", json={"default_currency": "USD", "date_format": "MDY"})
    assert r.status_code == 200 and r.json()["default_currency"] == "USD"
    assert admin.patch(f"/organizations/{admin.org_id}", json={"default_currency": "XXX"}).status_code == 422
