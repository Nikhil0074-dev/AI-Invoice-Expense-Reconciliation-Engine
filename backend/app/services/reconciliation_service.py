from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (BankTransaction, Document, Invoice, Organization, ReconciliationAllocation,
                        ReconciliationMatch, now)
from app.services import invoice_service
from app.services.audit import log_audit
from app.processors.normalize import currency_decimals
from app.services.matching import Candidate, InvoiceView, MatchConfig, TxView, score_candidates

CENT = Decimal("0.01")


def org_config(org: Organization) -> MatchConfig:
    return MatchConfig(high=org.match_high_threshold, review=org.match_review_threshold,
                       amount_tolerance_pct=org.amount_tolerance_pct, date_window_days=org.date_window_days)


def invoice_allocated(db: Session, invoice_id: str) -> Decimal:
    return db.scalar(select(func.coalesce(func.sum(ReconciliationAllocation.allocated_amount), 0))
                     .where(ReconciliationAllocation.invoice_id == invoice_id)) or Decimal(0)


def tx_allocated_map(db: Session, org_id: str, tx_ids: list[str] | None = None) -> dict[str, Decimal]:
    q = select(ReconciliationAllocation.bank_transaction_id, func.sum(ReconciliationAllocation.allocated_amount)) \
        .where(ReconciliationAllocation.organization_id == org_id).group_by(ReconciliationAllocation.bank_transaction_id)
    if tx_ids is not None:
        q = q.where(ReconciliationAllocation.bank_transaction_id.in_(tx_ids))
    return {k: Decimal(v) for k, v in db.execute(q).all()}


def tx_remaining(tx: BankTransaction, allocated: Decimal) -> Decimal:
    return abs(tx.amount) - allocated if tx.amount < 0 else Decimal(0)


def refresh_invoice_status(db: Session, inv: Invoice) -> None:
    allocated = invoice_allocated(db, inv.id)
    total = inv.total_amount or Decimal(0)
    if allocated <= 0:
        open_matches = db.scalar(select(func.count(ReconciliationMatch.id)).where(
            ReconciliationMatch.invoice_id == inv.id, ReconciliationMatch.match_status.in_(["SUGGESTED", "NEEDS_REVIEW"])))
        inv.reconciliation_status = "SUGGESTED" if open_matches else "UNMATCHED"
    elif allocated >= total - CENT / 2:
        inv.reconciliation_status = "CONFIRMED"
    else:
        inv.reconciliation_status = "PARTIALLY_RECONCILED"
    invoice_service.set_document_status(db, inv)


def _get_invoice(db: Session, org_id: str, invoice_id: str) -> Invoice:
    inv = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == org_id))
    if not inv:
        raise AppError("INVOICE_NOT_FOUND", "Invoice not found.", 404)
    return inv


def generate_suggestions(db: Session, org: Organization, inv: Invoice) -> list[ReconciliationMatch]:
    if inv.document.processing_status == "ARCHIVED":
        return []
    if inv.review_status != "VERIFIED" or inv.total_amount is None:
        raise AppError("INVOICE_NOT_VERIFIED", "Verify the invoice before generating reconciliation suggestions.", 409)
    remaining = inv.total_amount - invoice_allocated(db, inv.id)
    # drop previous open suggestions; keep rejected ones to avoid re-suggesting them
    for m in db.scalars(select(ReconciliationMatch).where(
            ReconciliationMatch.invoice_id == inv.id, ReconciliationMatch.match_status.in_(["SUGGESTED", "NEEDS_REVIEW"]))):
        db.delete(m)
    db.flush()
    if remaining <= CENT / 2:
        refresh_invoice_status(db, inv)
        return []
    rejected = {tuple(sorted(m.transaction_ids or [])) for m in db.scalars(select(ReconciliationMatch).where(
        ReconciliationMatch.invoice_id == inv.id, ReconciliationMatch.match_status == "REJECTED"))}
    txs = db.scalars(select(BankTransaction).where(BankTransaction.organization_id == org.id, BankTransaction.amount < 0)).all()
    alloc = tx_allocated_map(db, org.id)
    views = [TxView(t.id, t.transaction_date, t.normalized_description, t.description, t.reference, t.currency,
                    tx_remaining(t, alloc.get(t.id, Decimal(0)))) for t in txs]
    iv = InvoiceView(inv.id, inv.normalized_vendor_name or "", inv.invoice_number, inv.invoice_date, inv.due_date,
                     inv.currency, remaining)
    created = []
    for c in score_candidates(iv, views, org_config(org)):
        if tuple(sorted(c.tx_ids)) in rejected:
            continue
        m = ReconciliationMatch(organization_id=org.id, invoice_id=inv.id, kind=c.kind, match_status=c.status,
                                match_score=c.score, match_explanation=c.explanation,
                                signals={**c.signals, "plan": c.plan, "warnings": c.warnings}, transaction_ids=c.tx_ids)
        db.add(m)
        created.append(m)
    db.flush()
    refresh_invoice_status(db, inv)
    return created


def _validate_plan(db: Session, org_id: str, inv: Invoice, plan: list[dict]) -> list[tuple[BankTransaction, Decimal]]:
    if inv.review_status != "VERIFIED":
        raise AppError("INVOICE_NOT_VERIFIED", "The invoice must be verified before it can be reconciled.", 409)
    if not plan:
        raise AppError("EMPTY_ALLOCATION", "At least one transaction allocation is required.", 422)
    if inv.total_amount is None or inv.total_amount <= 0:
        raise AppError("INVALID_INVOICE_TOTAL", "Invoice must have a positive total amount before reconciliation.", 409)
    tx_ids = sorted({item["transaction_id"] for item in plan})
    if tx_ids:
        db.scalars(select(BankTransaction).where(
            BankTransaction.organization_id == org_id, BankTransaction.id.in_(tx_ids)
        ).order_by(BankTransaction.id).with_for_update()).all()
    seen, result, total_new = set(), [], Decimal(0)
    for item in plan:
        tid, amount = item["transaction_id"], Decimal(str(item["amount"]))
        if tid in seen:
            raise AppError("DUPLICATE_TRANSACTION", "A transaction can only appear once per match.", 422)
        seen.add(tid)
        if amount <= 0:
            raise AppError("INVALID_ALLOCATION", "Allocated amounts must be positive.", 422)
        tx = db.scalar(select(BankTransaction).where(BankTransaction.id == tid, BankTransaction.organization_id == org_id))
        if not tx:
            raise AppError("TRANSACTION_NOT_FOUND", "Transaction not found.", 404)
        if tx.currency != inv.currency:
            raise AppError("CURRENCY_MISMATCH", f"Transaction currency {tx.currency} differs from invoice currency {inv.currency}. "
                           "Cross-currency reconciliation is not supported in this version.", 409)
        if tx.amount >= 0:
            raise AppError("NOT_AN_OUTFLOW", "Only outgoing transactions can settle an invoice.", 409)
        if amount.normalize().as_tuple().exponent < -currency_decimals(tx.currency):
            raise AppError("INVALID_ALLOCATION", f"Allocated amounts must use at most {currency_decimals(tx.currency)} decimal places for {tx.currency}.", 422)
        avail = tx_remaining(tx, tx_allocated_map(db, org_id, [tid]).get(tid, Decimal(0)))
        if amount > avail:
            raise AppError("OVER_ALLOCATION", f"Transaction has only {avail} left to allocate.", 409)
        result.append((tx, amount))
        total_new += amount
    inv_rem = (inv.total_amount or Decimal(0)) - invoice_allocated(db, inv.id)
    if total_new > inv_rem:
        raise AppError("OVER_ALLOCATION", f"Invoice has only {inv_rem} left to reconcile.", 409)
    return result


def confirm_match(db: Session, org: Organization, match: ReconciliationMatch, user_id: str) -> ReconciliationMatch:
    match = db.scalar(select(ReconciliationMatch).where(ReconciliationMatch.id == match.id).with_for_update())
    if not match:
        raise AppError("MATCH_NOT_FOUND", "Match not found.", 404)
    if match.match_status in ("CONFIRMED", "PARTIALLY_RECONCILED"):
        raise AppError("ALREADY_CONFIRMED", "This match is already confirmed.", 409)
    inv = db.scalar(select(Invoice).where(Invoice.id == match.invoice_id, Invoice.organization_id == org.id).with_for_update())
    if not inv:
        raise AppError("INVOICE_NOT_FOUND", "Invoice not found.", 404)
    plan = (match.signals or {}).get("plan", [])
    rem = (inv.total_amount or Decimal(0)) - invoice_allocated(db, inv.id)
    # re-plan against the current state (other matches may have been confirmed since the suggestion)
    fresh, left = [], rem
    for p in plan:
        tx = db.get(BankTransaction, p["transaction_id"])
        avail = tx_remaining(tx, tx_allocated_map(db, org.id, [tx.id]).get(tx.id, Decimal(0))) if tx else Decimal(0)
        amt = min(Decimal(p["amount"]), avail, left)
        if amt > 0:
            fresh.append({"transaction_id": tx.id, "amount": amt})
            left -= amt
    validated = _validate_plan(db, org.id, inv, fresh)
    for tx, amt in validated:
        db.add(ReconciliationAllocation(organization_id=org.id, match_id=match.id, invoice_id=inv.id,
                                        bank_transaction_id=tx.id, allocated_amount=amt, currency=tx.currency))
    match.match_status = "CONFIRMED"
    match.confirmed_by, match.confirmed_at = user_id, datetime.now(timezone.utc)
    db.flush()
    # other open suggestions are stale now
    for m in db.scalars(select(ReconciliationMatch).where(
            ReconciliationMatch.invoice_id == inv.id, ReconciliationMatch.id != match.id,
            ReconciliationMatch.match_status.in_(["SUGGESTED", "NEEDS_REVIEW"]))):
        db.delete(m)
    db.flush()
    refresh_invoice_status(db, inv)
    if inv.reconciliation_status == "PARTIALLY_RECONCILED":
        match.match_status = "PARTIALLY_RECONCILED"
    log_audit(db, org.id, user_id, "reconciliation_match", match.id, "match.confirm", None,
              {"invoice_id": inv.id, "allocations": [{"transaction_id": t.id, "amount": format(a, "f")} for t, a in validated]})
    return match


def manual_match(db: Session, org: Organization, invoice_id: str, plan: list[dict], user_id: str) -> ReconciliationMatch:
    inv = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == org.id).with_for_update())
    if not inv:
        raise AppError("INVOICE_NOT_FOUND", "Invoice not found.", 404)
    validated = _validate_plan(db, org.id, inv, plan)
    m = ReconciliationMatch(organization_id=org.id, invoice_id=inv.id, kind="MANUAL", match_status="CONFIRMED", match_score=None,
                            match_explanation="Manually linked by a user.", transaction_ids=[t.id for t, _ in validated],
                            signals={"plan": [{"transaction_id": t.id, "amount": format(a, "f")} for t, a in validated]},
                            confirmed_by=user_id, confirmed_at=datetime.now(timezone.utc))
    db.add(m)
    db.flush()
    for tx, amt in validated:
        db.add(ReconciliationAllocation(organization_id=org.id, match_id=m.id, invoice_id=inv.id,
                                        bank_transaction_id=tx.id, allocated_amount=amt, currency=tx.currency))
    db.flush()
    refresh_invoice_status(db, inv)
    if inv.reconciliation_status == "PARTIALLY_RECONCILED":
        m.match_status = "PARTIALLY_RECONCILED"
    log_audit(db, org.id, user_id, "reconciliation_match", m.id, "match.manual", None, {"invoice_id": inv.id, "plan": m.signals["plan"]})
    return m


def reject_match(db: Session, org: Organization, match: ReconciliationMatch, user_id: str) -> ReconciliationMatch:
    if match.match_status in ("CONFIRMED", "PARTIALLY_RECONCILED"):
        raise AppError("MATCH_CONFIRMED", "Unlink a confirmed match instead of rejecting it.", 409)
    match.match_status = "REJECTED"
    db.flush()
    inv = _get_invoice(db, org.id, match.invoice_id)
    refresh_invoice_status(db, inv)
    log_audit(db, org.id, user_id, "reconciliation_match", match.id, "match.reject", None, {"invoice_id": inv.id})
    return match


def unlink_match(db: Session, org: Organization, match: ReconciliationMatch, user_id: str) -> ReconciliationMatch:
    if match.match_status not in ("CONFIRMED", "PARTIALLY_RECONCILED"):
        raise AppError("MATCH_NOT_CONFIRMED", "Only confirmed matches can be unlinked.", 409)
    before = {"allocations": [{"transaction_id": a.bank_transaction_id, "amount": format(a.allocated_amount, "f")}
                              for a in db.scalars(select(ReconciliationAllocation).where(ReconciliationAllocation.match_id == match.id))]}
    for a in db.scalars(select(ReconciliationAllocation).where(ReconciliationAllocation.match_id == match.id)):
        db.delete(a)
    match.match_status = "REJECTED"
    match.match_explanation += " (Unlinked by a user.)"
    match.confirmed_by = match.confirmed_at = None
    db.flush()
    inv = _get_invoice(db, org.id, match.invoice_id)
    refresh_invoice_status(db, inv)
    log_audit(db, org.id, user_id, "reconciliation_match", match.id, "match.unlink", before, {"match_status": "REJECTED"})
    return match
