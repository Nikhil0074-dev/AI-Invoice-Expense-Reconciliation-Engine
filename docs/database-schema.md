# Database schema

Created by Alembic revision `0001` (`backend/migrations`). Monetary columns are `NUMERIC(18,4)`; ids are UUID strings.

| Table | Purpose / key points |
|---|---|
| users, organizations, organization_members | accounts, workspaces (currency, locale, date format, matching thresholds), roles; unique (org, user) |
| documents | file metadata, `storage_key` (internal), `content_sha256`, status, extraction method/confidence. Index (org, created_at), (org, sha256) |
| processing_jobs | attempts, max_attempts, error_code/message, timestamps |
| invoices | extracted+corrected fields, `extraction_original` (immutable JSON), per-field confidence, uncertain fields, validation warnings, review & reconciliation status. Index (org, invoice_date), (org, normalized_vendor_name) |
| invoice_line_items | optional line items |
| import_batches, bank_transactions | CSV imports; negative amount = outflow; unique (org, fingerprint) prevents repeat imports; index (org, date) |
| reconciliation_matches | suggestion/decision with score, explanation, signals, transaction ids; index (org, status) |
| reconciliation_allocations | invoice ↔ transaction amounts (split & partial payments); sums validated against both sides |
| duplicate_flags | pair + method (FILE_HASH, INVOICE_IDENTITY, FUZZY) + category + evidence + review; unique (doc, other, method) |
| audit_logs | actor, entity, action, before/after JSON (no secrets, no raw text) |
| exports | export metadata: type, filters, row count, SHA-256 of the generated file |
