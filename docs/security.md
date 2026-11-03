# Security notes

- **Uploads**: signature (magic-byte) check, not file extension; size limit enforced while streaming; PDFs with `/JavaScript`,
  `/Launch`, `/EmbeddedFile` rejected; generated storage keys; files never served statically — previews/downloads go through
  authenticated endpoints with `nosniff` and `no-store`; filenames sanitised; page-count limit and OCR timeout.
- **AuthN**: scrypt password hashes, short-lived HS256 JWTs (reset tokens have a different `typ` and cannot be used as access tokens),
  login/register/reset rate-limited, no account enumeration on reset, production refuses to start with the default `SECRET_KEY`.
- **AuthZ**: organization scoping on every query, RBAC on every route, regression tests for cross-organization access (`tests/integration/test_auth_and_isolation.py`).
- **Financial integrity**: `Decimal` everywhere, allocation over-/double-spend checks, currency checks, confirmation required for
  every consequential action, original extraction preserved, audit trail for corrections, matches, duplicate decisions and exports.
- **CSV injection**: text cells beginning with `= + - @ TAB CR` are prefixed with `'`; numeric/date cells are never altered.
- **Errors/logging**: tracebacks go to logs only; API errors carry codes, not internals; audit logs exclude passwords, tokens and document text.
- **Not included**: antivirus scanning, email verification/MFA, encryption at rest (use disk/DB encryption), secrets manager,
  provider-token storage (no bank provider integrated). If you add an external OCR provider, disclose it and review its retention terms.
