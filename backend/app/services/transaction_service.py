"""Bank CSV import with configurable mapping, explicit sign convention and repeat-import protection."""
import csv
import hashlib
import io
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import BankTransaction, ImportBatch, Organization
from app.processors.normalize import ISO_CURRENCIES, detect_decimal_style, normalize_vendor, parse_amount, parse_date, quantize_money

MAX_ROWS = 50_000
SYNONYMS = {
    "date": ["transaction date", "txn date", "value date", "posting date", "booking date", "date", "datum"],
    "description": ["description", "narration", "details", "merchant", "particulars", "payee", "memo", "remarks", "beschreibung", "verwendungszweck"],
    "amount": ["amount", "transaction amount", "betrag", "value"],
    "debit": ["debit", "withdrawal", "withdrawals", "debit amount", "dr", "paid out", "money out"],
    "credit": ["credit", "deposit", "deposits", "credit amount", "cr", "paid in", "money in"],
    "currency": ["currency", "ccy", "cur", "währung"],
    "reference": ["reference", "ref", "ref no", "transaction id", "txn id", "utr", "cheque no", "reference number", "chq/ref no"],
    "account": ["account", "account number", "account no", "account id", "iban"],
}


def decode_csv(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise AppError("CSV_ENCODING", "Could not decode the CSV file.", 400)


def read_rows(data: bytes) -> tuple[list[str], list[dict]]:
    text = decode_csv(data)
    if not text.strip():
        raise AppError("EMPTY_CSV", "The CSV file is empty.", 400)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h.strip() for h in (reader.fieldnames or []) if h is not None]
    if not headers:
        raise AppError("EMPTY_CSV", "No header row found.", 400)
    rows = []
    for r in reader:
        rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items() if k is not None})
        if len(rows) > MAX_ROWS:
            raise AppError("CSV_TOO_LARGE", f"CSV exceeds {MAX_ROWS} rows.", 413)
    return headers, rows


def guess_mapping(headers: list[str]) -> dict:
    low = {h.lower(): h for h in headers}
    mapping = {}
    for key, names in SYNONYMS.items():
        for n in names:
            if n in low:
                mapping[key] = low[n]
                break
    return mapping


def preview(data: bytes) -> dict:
    headers, rows = read_rows(data)
    return {"headers": headers, "suggested_mapping": guess_mapping(headers), "sample_rows": rows[:5], "row_count": len(rows)}


def import_transactions(db: Session, org: Organization, user_id: str, filename: str, data: bytes, mapping: dict | None,
                        sign_convention: str = "negative_is_outflow", date_format: str | None = None,
                        default_currency: str | None = None, dry_run: bool = False) -> dict:
    if sign_convention not in ("negative_is_outflow", "positive_is_outflow"):
        raise AppError("INVALID_SIGN_CONVENTION", "sign_convention must be negative_is_outflow or positive_is_outflow.", 422)
    headers, rows = read_rows(data)
    mapping = {**guess_mapping(headers), **(mapping or {})}
    for key in ("date", "description"):
        if not mapping.get(key) or mapping[key] not in headers:
            raise AppError("MAPPING_REQUIRED", f"Column mapping for '{key}' is missing or not in the file.", 422, {"field": key})
    has_split = bool(mapping.get("debit") or mapping.get("credit"))
    if has_split:
        for key in ("debit", "credit"):
            if mapping.get(key) and mapping[key] not in headers:
                raise AppError("MAPPING_REQUIRED", f"Mapped '{key}' column is not in the file.", 422, {"field": key})
    elif not mapping.get("amount") or mapping["amount"] not in headers:
        raise AppError("MAPPING_REQUIRED", "Map either an 'amount' column or 'debit'/'credit' columns.", 422)
    cur_default = (default_currency or org.default_currency).upper()
    if cur_default not in ISO_CURRENCIES:
        raise AppError("INVALID_CURRENCY", f"Unsupported default currency '{cur_default}'.", 422)
    fmt = (date_format or org.date_format).upper()

    def col(row, key):
        c = mapping.get(key)
        return row.get(c, "") if c else ""

    amount_cols = [col(r, "amount") for r in rows] + [col(r, "debit") for r in rows] + [col(r, "credit") for r in rows]
    hint = detect_decimal_style([a for a in amount_cols if a])

    existing = {fp for (fp,) in db.execute(select(BankTransaction.fingerprint).where(BankTransaction.organization_id == org.id))}
    batch = ImportBatch(organization_id=org.id, filename=filename[:255], mapping=mapping, created_by=user_id, row_count=len(rows))
    db.add(batch)
    db.flush()
    seen_count: dict[tuple, int] = {}
    errors, imported, skipped, preview_rows = [], 0, 0, []
    for n, row in enumerate(rows, start=2):  # row 1 is the header
        d, _ = parse_date(col(row, "date"), fmt)
        if not d:
            errors.append({"row": n, "message": f"Unparseable date '{col(row, 'date')}'"})
            continue
        if has_split:
            deb, cred = parse_amount(col(row, "debit"), hint), parse_amount(col(row, "credit"), hint)
            if deb is not None and cred is not None and deb != 0 and cred != 0:
                errors.append({"row": n, "message": "Both debit and credit amounts are set"})
                continue
            if deb is None and cred is None:
                errors.append({"row": n, "message": "Neither debit nor credit amount found"})
                continue
            amount = -abs(deb) if deb is not None and deb != 0 else (abs(cred) if cred is not None else Decimal(0))
        else:
            raw = parse_amount(col(row, "amount"), hint)
            if raw is None:
                errors.append({"row": n, "message": f"Unparseable amount '{col(row, 'amount')}'"})
                continue
            amount = raw if sign_convention == "negative_is_outflow" else -raw
        cur = (col(row, "currency") or cur_default).upper().strip()
        if cur not in ISO_CURRENCIES:
            errors.append({"row": n, "message": f"Unknown currency '{cur}'"})
            continue
        amount = quantize_money(amount, cur)
        desc = col(row, "description")[:500]
        ref = col(row, "reference")[:100] or None
        acct = col(row, "account")[:100] or None
        key = (acct or "", d.isoformat(), format(amount, "f"), cur, desc.lower(), ref or "")
        idx = seen_count.get(key, 0)
        seen_count[key] = idx + 1
        fp = hashlib.sha256(("|".join(key) + f"|{org.id}|{idx}").encode()).hexdigest()
        if fp in existing:
            skipped += 1
            continue
        existing.add(fp)
        imported += 1
        if len(preview_rows) < 5:
            preview_rows.append({"date": d.isoformat(), "description": desc, "amount": format(amount, "f"), "currency": cur})
        if not dry_run:
            db.add(BankTransaction(organization_id=org.id, source_type="CSV", fingerprint=fp, transaction_date=d,
                                   description=desc, normalized_description=normalize_vendor(desc, bank_description=True),
                                   amount=amount, currency=cur, reference=ref, source_transaction_id=ref, account=acct,
                                   import_batch_id=batch.id))
    batch.imported_count, batch.skipped_count, batch.error_count = imported, skipped, len(errors)
    if dry_run:
        db.rollback()
    return {"batch_id": None if dry_run else batch.id, "dry_run": dry_run, "row_count": len(rows), "imported": imported,
            "skipped_duplicates": skipped, "errors": errors[:100], "error_count": len(errors), "sample": preview_rows,
            "mapping": mapping, "sign_convention": sign_convention}
