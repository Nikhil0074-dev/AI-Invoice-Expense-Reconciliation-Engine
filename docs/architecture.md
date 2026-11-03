# Architecture

```
React + TS (Vite, Tailwind, PDF.js, Recharts)
        │ REST /api/v1  (Bearer JWT + X-Organization-Id)
FastAPI ── auth, RBAC, validation, services
   │  ├─ PostgreSQL / SQLite (SQLAlchemy 2, Alembic)
   │  ├─ Private file storage (LocalStorage behind StorageBackend)
   │  └─ Job queue: inline | FastAPI BackgroundTasks | Celery+Redis
Worker (run_job): extract → parse → validate → duplicate check → status
```

## Layering (backend/app)
| Package | Responsibility |
|---|---|
| `api/v1` | HTTP only: parse request, call a service, shape the response |
| `core` | settings, security (scrypt, JWT, rate limiter), permissions, error format |
| `processors` | `pdf_extractor` (native text first, OCR fallback), `ocr_service` (provider interface + Tesseract), `image_preprocessor`, `invoice_parser`, `normalize`, `validators` |
| `services` | `document`, `invoice`, `duplicate`, `matching` (pure scoring), `reconciliation`, `transaction` (CSV), `export`, `dashboard`, `audit` |
| `workers` | `document_tasks.run_job` (idempotent, bounded retries), optional `celery_app` |
| `integrations` | `storage` interface |

## State model — extracted ≠ suggested ≠ confirmed ≠ finalized
- **Extraction** (`invoices.extraction_original` is immutable) → corrections are separate columns + audit rows.
- **Invoice review_status**: `REVIEW_REQUIRED` → (human) `VERIFIED`. Nothing is exported or reconciled before verification.
- **Document status**: `UPLOADED → QUEUED → PROCESSING → REVIEW_REQUIRED | DUPLICATE_REVIEW → READY_FOR_RECONCILIATION → RECONCILED`,
  plus `FAILED` and `ARCHIVED` (confirmed duplicate — kept, excluded from totals/exports).
- **Match status**: `SUGGESTED | NEEDS_REVIEW` (engine) → `CONFIRMED | PARTIALLY_RECONCILED` (human) or `REJECTED`.
  Confirmed matches create rows in `reconciliation_allocations`; those are the source of truth for amounts.

## Processing job
`POST /documents` stores the file, writes `documents` + `processing_jobs`, enqueues. `run_job`:
1. skips if the job already `SUCCEEDED` (idempotent);
2. transient errors (`OCR_TIMEOUT`, storage read) retry with exponential back-off up to `JOB_MAX_ATTEMPTS`;
3. permanent errors (`UNREADABLE_DOCUMENT`, `ENCRYPTED_PDF`, `PAGE_LIMIT_EXCEEDED`, `NO_TEXT_FOUND`) fail immediately with a safe code;
4. all DB writes for one attempt commit together, so a crash never leaves half an invoice.

## Reconciliation scoring
`S = 0.45·A + 0.25·V + 0.20·D + 0.10·R` (see `services/matching.py`).
A: exact = 1, within tolerance 0.9→0.5, partial payments ≤ 0.6, different currency = 0.
V: RapidFuzz token-set ratio on normalised vendor vs. bank description (legal suffixes and bank noise words removed).
D: 1.0 within 3 days of invoice/due date, decaying linearly over the configured window.
R: invoice number found inside the transaction text/reference.
Partial/split/currency-mismatch candidates are capped to *needs review*; ≥ high threshold and clean ⇒ `SUGGESTED`.
Weights are design defaults, not validated constants.

## Authorization
Every row carries `organization_id`; every query filters on the caller's organization (resolved from membership, not from
the client's claim). Cross-organization IDs return 404; a forged `X-Organization-Id` returns 403. Roles map to permission
sets in `core/permissions.py` (mirrored in the UI only to hide buttons — the server is the authority).
