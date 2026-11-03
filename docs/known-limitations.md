# Known limitations

Stated plainly so nobody over-trusts the system.

**Extraction**
- Rule-based parsing handles common English, German, French and Spanish labels. Unusual layouts, multi-column tables,
  handwriting and very poor scans need manual correction (that is what the review screen is for).
- Table layouts whose line items are split across several text lines are not reconstructed; line items are optional.
- Only the `eng` Tesseract pack is guaranteed locally. The Docker image installs eng/deu/fra/spa/hin; set `OCR_LANGUAGES`
  (e.g. `eng+deu`). OCR accuracy on non-Latin scripts has **not** been measured.
- A bare `$` is treated as USD but flagged as uncertain (it could be AUD, CAD, SGD...).
- Page-boundary detection and deskewing beyond EXIF orientation are not implemented.
- No accuracy percentage is claimed: the repository contains a small synthetic set for regression tests, not a benchmark.
  Measure extraction/match precision on your own labelled data before relying on it (see `docs/testing.md`).

**Reconciliation**
- Only same-currency matching is supported; cross-currency candidates are surfaced as warnings and cannot be confirmed.
- Weights (0.45/0.25/0.20/0.10) and thresholds are untuned defaults. ML-assisted ranking is not implemented.
- Allocation never "forgives" a small difference: paying 5,799.50 against 5,800.00 leaves the invoice *partially reconciled*.
- Split-payment search considers combinations of up to 3 transactions.
- Inflows/refunds/credit notes are not matched to invoices.

**Platform**
- SQLite is for development/tests only (money is stored as exact NUMERIC only on PostgreSQL).
- Docker files, PostgreSQL and the Celery/Redis path were written to be correct but **could not be executed in the build
  sandbox** (no Docker daemon, PostgreSQL or Redis). The default `inline`/`background` modes, SQLite and Alembic were exercised.
- Storage is local disk behind an interface; an S3-compatible adapter is not included.
- Password reset has no email delivery; outside production the token is returned by the API so the flow is testable.
- Rate limiting is in-process memory; use a gateway/Redis limiter for multi-process deployments.
- Upload scanning is a heuristic (rejects PDFs with `/JavaScript`, `/Launch`, `/EmbeddedFile`). Plug in ClamAV for real scanning.
- No bank-provider connection (Plaid etc.), no email ingestion, no automatic data-retention purge, no categorisation AI.
- Exports are generic CSVs with two header presets; they are not validated against any specific accounting product's importer.
- Raw extracted text is stored on the invoice row for reprocessing/debugging; treat the database as sensitive.
