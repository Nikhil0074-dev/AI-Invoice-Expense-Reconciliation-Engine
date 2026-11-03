import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="invoice-tests-")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db", "STORAGE_DIR": f"{_tmp}/storage", "PROCESSING_MODE": "inline",
    "ENVIRONMENT": "test", "JOB_RETRY_BACKOFF_SECONDS": "0", "RATE_LIMIT_PER_MINUTE": "1000",
    "SECRET_KEY": "test-secret-key-that-is-long-enough-for-hs256-1234567890",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402,F401
from app.core.security import rate_limiter  # noqa: E402
from app.db import session as dbs  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(dbs.engine)
    Base.metadata.create_all(dbs.engine)
    rate_limiter.reset()
    yield


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


class Session:
    """Helper bound to one user + organization."""

    def __init__(self, client, token, org_id):
        self.c, self.org_id = client, org_id
        self.h = {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id}

    def get(self, url, **kw):
        return self.c.get("/api/v1" + url, headers=self.h, **kw)

    def post(self, url, **kw):
        return self.c.post("/api/v1" + url, headers=self.h, **kw)

    def patch(self, url, **kw):
        return self.c.patch("/api/v1" + url, headers=self.h, **kw)

    def delete(self, url, **kw):
        return self.c.delete("/api/v1" + url, headers=self.h, **kw)

    def upload(self, data: bytes, name="invoice.pdf", ctype="application/pdf"):
        return self.post("/documents", files={"file": (name, data, ctype)})

    def import_csv(self, text: str, **form):
        return self.post("/transactions/import", files={"file": ("bank.csv", text.encode(), "text/csv")}, data=form)


def make_user(client, email, org_name="Acme Ltd", password="Passw0rd!x") -> Session:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password, "display_name": email.split("@")[0],
                                                    "organization_name": org_name})
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    orgs = client.get("/api/v1/organizations", headers={"Authorization": f"Bearer {token}"}).json()
    return Session(client, token, orgs[0]["id"])


@pytest.fixture
def admin(client):
    return make_user(client, "admin@acme.example.com")


def add_member(client, admin: Session, email: str, role: str) -> Session:
    other = make_user(client, email, org_name=f"{email} own org")
    r = admin.post(f"/organizations/{admin.org_id}/members", json={"email": email, "role": role})
    assert r.status_code == 201, r.text
    return Session(client, other.h["Authorization"].split()[1], admin.org_id)


def upload_and_verify(s: Session, data: bytes, name="inv.pdf", **patch):
    r = s.upload(data, name)
    assert r.status_code == 201, r.text
    doc = s.get(f"/documents/{r.json()['document_id']}").json()
    inv_id = doc["invoice_id"]
    if patch:
        assert s.patch(f"/invoices/{inv_id}", json=patch).status_code == 200
    v = s.post(f"/invoices/{inv_id}/verify", json={"acknowledge_warnings": True})
    assert v.status_code == 200, v.text
    return inv_id, doc
