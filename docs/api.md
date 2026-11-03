# API reference

Interactive OpenAPI: `http://localhost:8000/docs` (Swagger) and `/redoc`. Base path `/api/v1`.
Auth: `Authorization: Bearer <token>`; org-scoped endpoints also need `X-Organization-Id` (optional when the user has exactly one org).
Money is always a decimal **string**. Errors: `{"error": {"code", "message", "details"}}` with 400/401/403/404/409/413/422/429/500.

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register`, `/auth/login`, `GET /auth/me`, `POST /auth/password-reset/request`, `/auth/password-reset/confirm` |
| Organizations | `GET/POST /organizations`, `GET/PATCH /organizations/{id}`, `GET/POST /organizations/{id}/members`, `PATCH/DELETE …/members/{member_id}` |
| Documents | `POST /documents` (multipart `file`), `GET /documents` (filters: q, status, currency, date_from/to, min/max_amount, sort, page), `GET /documents/{id}`, `/preview`, `/download`, `POST /documents/{id}/process`, `DELETE /documents/{id}`, `GET /jobs/{id}` |
| Invoices | `GET /invoices` (needs_review, review_status, reconciliation_status, …), `GET/PATCH /invoices/{id}`, `GET …/line-items`, `POST …/verify` |
| Transactions | `POST /transactions/import/preview`, `POST /transactions/import` (mapping, sign_convention, date_format, default_currency, dry_run), `GET /transactions` |
| Reconciliation | `GET /reconciliation/suggestions?invoice_id=`, `POST /reconciliation/run`, `GET /reconciliation/matches`, `POST /reconciliation/matches` (`match_id` **or** `invoice_id`+`allocations`), `PATCH …/matches/{id}` (`confirm`/`unlink`), `POST …/matches/{id}/reject` |
| Duplicates | `GET /duplicates?status=`, `POST /duplicates/{id}/review` (`dismiss` / `confirm_duplicate`) |
| Exports | `POST /exports/csv`, `GET /exports`, `/exports/templates`, `/exports/{id}`, `/exports/{id}/download` |
| Other | `GET /dashboard`, `GET /audit-logs`, `GET /health` |

## Example: upload → review → verify
```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"DemoPass123"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s -H "Authorization: Bearer $TOKEN" -F file=@invoice.pdf localhost:8000/api/v1/documents
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/invoices?needs_review=true
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"acknowledge_warnings":true}' localhost:8000/api/v1/invoices/<id>/verify
```

## Notable error codes
`UNSUPPORTED_FILE_TYPE`, `ACTIVE_CONTENT_REJECTED`, `FILE_TOO_LARGE` (413), `VERIFICATION_BLOCKED` (422), `WARNINGS_NOT_ACKNOWLEDGED`,
`DUPLICATE_REVIEW_PENDING`, `INVOICE_NOT_VERIFIED`, `INVOICE_RECONCILED`, `OVER_ALLOCATION`, `CURRENCY_MISMATCH`, `NOT_AN_OUTFLOW`,
`EXPORT_VALIDATION_FAILED`, `LAST_ADMIN`, `RATE_LIMITED` (429).
