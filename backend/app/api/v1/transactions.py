import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import case, func, or_, select

from app.api.deps import Ctx, require
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import BankTransaction, ReconciliationAllocation
from app.schemas import TransactionOut
from app.services import document_service, transaction_service
from app.services.audit import log_audit
from app.services.reconciliation_service import tx_allocated_map, tx_remaining

router = APIRouter(prefix="/transactions", tags=["transactions"])


def tx_out(t: BankTransaction, allocated: Decimal) -> TransactionOut:
    out = TransactionOut.model_validate(t)
    out.allocated = allocated
    out.remaining = tx_remaining(t, allocated) if t.amount < 0 else Decimal(0)
    if t.amount >= 0:
        out.status = "INFLOW"
    elif allocated <= 0:
        out.status = "UNMATCHED"
    elif out.remaining > Decimal("0.005"):
        out.status = "PARTIALLY_RECONCILED"
    else:
        out.status = "RECONCILED"
    return out


async def _read_csv(file: UploadFile, ctx: Ctx) -> bytes:
    data = await document_service.read_limited(file, min(ctx.org.max_upload_mb, get_settings().max_upload_mb) * 1024 * 1024)
    if data[:5] == b"%PDF-" or data[:4] == b"\x89PNG" or data[:3] == b"\xff\xd8\xff":
        raise AppError("UNSUPPORTED_FILE_TYPE", "This endpoint accepts CSV files only.", 400)
    return data


@router.post("/import/preview")
async def import_preview(file: UploadFile = File(...), ctx: Ctx = Depends(require("transactions:import"))):
    return transaction_service.preview(await _read_csv(file, ctx))


@router.post("/import")
async def import_csv(file: UploadFile = File(...), mapping: str | None = Form(None), sign_convention: str = Form("negative_is_outflow"),
                     date_format: str | None = Form(None), default_currency: str | None = Form(None), dry_run: bool = Form(False),
                     ctx: Ctx = Depends(require("transactions:import"))):
    data = await _read_csv(file, ctx)
    try:
        mp = json.loads(mapping) if mapping else None
        if mp is not None and not isinstance(mp, dict):
            raise ValueError
    except ValueError:
        raise AppError("INVALID_MAPPING", "mapping must be a JSON object.", 422)
    res = transaction_service.import_transactions(ctx.db, ctx.org, ctx.user.id, file.filename or "transactions.csv", data, mp,
                                                  sign_convention, date_format, default_currency, dry_run)
    if not dry_run:
        log_audit(ctx.db, ctx.org.id, ctx.user.id, "import_batch", res["batch_id"], "transactions.import", None,
                  {"imported": res["imported"], "skipped": res["skipped_duplicates"], "errors": res["error_count"]})
        ctx.db.commit()
    return res


@router.get("")
def list_transactions(q: str | None = None, status: str | None = None, date_from: date | None = None, date_to: date | None = None,
                      currency: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                      ctx: Ctx = Depends(require("transactions:read"))):
    db = ctx.db
    stmt = select(BankTransaction).where(BankTransaction.organization_id == ctx.org.id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(BankTransaction.description.ilike(like), BankTransaction.reference.ilike(like)))
    if date_from:
        stmt = stmt.where(BankTransaction.transaction_date >= date_from)
    if date_to:
        stmt = stmt.where(BankTransaction.transaction_date <= date_to)
    if currency:
        stmt = stmt.where(BankTransaction.currency == currency.upper())
    allocation_totals = select(
        ReconciliationAllocation.bank_transaction_id.label("tx_id"),
        func.sum(ReconciliationAllocation.allocated_amount).label("allocated"),
    ).where(ReconciliationAllocation.organization_id == ctx.org.id).group_by(ReconciliationAllocation.bank_transaction_id).subquery()
    allocated = func.coalesce(allocation_totals.c.allocated, 0)
    status_expr = case(
        (BankTransaction.amount >= 0, "INFLOW"),
        (allocated <= 0, "UNMATCHED"),
        (func.abs(BankTransaction.amount) - allocated > Decimal("0.005"), "PARTIALLY_RECONCILED"),
        else_="RECONCILED",
    )
    stmt = stmt.outerjoin(allocation_totals, allocation_totals.c.tx_id == BankTransaction.id)
    if status:
        stmt = stmt.where(status_expr == status.upper())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(BankTransaction.transaction_date.desc(), BankTransaction.created_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    alloc = tx_allocated_map(db, ctx.org.id, [t.id for t in rows])
    return {"items": [tx_out(t, alloc.get(t.id, Decimal(0))) for t in rows], "total": total, "page": page, "page_size": page_size}
