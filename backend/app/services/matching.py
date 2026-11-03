"""Pure, DB-free scoring for invoice <-> bank transaction matching.

S = 0.45*A + 0.25*V + 0.20*D + 0.10*R   (initial design weights, to be tuned on labelled data)
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import combinations

from rapidfuzz import fuzz

from app.processors.normalize import alnum, normalize_vendor

WEIGHTS = (0.45, 0.25, 0.20, 0.10)
CENT = Decimal("0.01")


@dataclass
class MatchConfig:
    high: float = 0.80
    review: float = 0.55
    amount_tolerance_pct: float = 0.02
    date_window_days: int = 30


@dataclass
class InvoiceView:
    id: str
    vendor_norm: str
    number: str | None
    date: date | None
    due_date: date | None
    currency: str | None
    remaining: Decimal  # still to be reconciled


@dataclass
class TxView:
    id: str
    date: date
    description_norm: str
    description_raw: str
    reference: str | None
    currency: str
    remaining: Decimal  # absolute outflow still unallocated


@dataclass
class Candidate:
    kind: str  # SINGLE | PARTIAL | SPLIT
    tx_ids: list[str]
    plan: list[dict]
    score: float
    status: str  # SUGGESTED | NEEDS_REVIEW
    signals: dict
    explanation: str
    warnings: list[str] = field(default_factory=list)


def amount_score(target: Decimal, amount: Decimal, tol_pct: float) -> float:
    diff = abs(target - amount)
    if diff <= CENT / 2:
        return 1.0
    if target == 0:
        return 0.0
    rel = float(diff / target)
    if rel <= tol_pct:
        return round(0.9 - 0.4 * (rel / tol_pct), 4)
    return 0.0


def vendor_score(inv_vendor_norm: str, tx_desc_norm: str) -> float:
    if not inv_vendor_norm or not tx_desc_norm:
        return 0.0
    return round(fuzz.token_set_ratio(inv_vendor_norm, tx_desc_norm) / 100.0, 4)


def date_score(inv: InvoiceView, tx_date: date, window: int) -> tuple[float, int | None]:
    refs = [d for d in (inv.date, inv.due_date) if d]
    if not refs:
        return 0.0, None

    def eff(days: int) -> int:
        if 0 <= days <= 3:
            return 0
        return days - 3 if days > 3 else abs(days) + 3

    best = min(((eff((tx_date - r).days), (tx_date - r).days) for r in refs), key=lambda x: x[0])
    return round(max(0.0, 1 - best[0] / max(window, 1)), 4), (tx_date - inv.date).days if inv.date else best[1]


def reference_score(number: str | None, tx: TxView) -> float:
    n = alnum(number)
    if len(n) < 4:
        return 0.0
    return 1.0 if n in alnum(tx.description_raw) or n in alnum(tx.reference) else 0.0


def _explain(kind: str, parts: dict, inv_cur: str | None, txs: list[TxView], days: int | None, a_note: str) -> str:
    bits = []
    if kind == "SPLIT":
        bits.append(f"{len(txs)} transactions together add up to the remaining invoice amount")
    elif a_note:
        bits.append(a_note)
    v = parts["vendor"]
    bits.append("the vendor description is " + ("an exact/near match" if v >= 0.9 else "similar" if v >= 0.6 else "only weakly similar" if v > 0 else "not similar"))
    if days is not None:
        if 0 <= days <= 3:
            bits.append("the payment is within 3 days of the invoice date" if days else "the payment is on the invoice date")
        elif days > 0:
            bits.append(f"the transaction occurred {days} days after the invoice date")
        else:
            bits.append(f"the transaction occurred {abs(days)} days before the invoice date")
    if parts["reference"] >= 1:
        bits.append("the invoice number appears in the transaction reference")
    return "Suggested because " + ", ".join(bits) + "."


def score_candidates(inv: InvoiceView, txs: list[TxView], cfg: MatchConfig, max_results: int = 5) -> list[Candidate]:
    wA, wV, wD, wR = WEIGHTS
    out: list[Candidate] = []
    singles_for_split: list[tuple[TxView, float, float]] = []
    for tx in txs:
        if tx.remaining <= 0:
            continue
        v = vendor_score(inv.vendor_norm, tx.description_norm)
        d, days = date_score(inv, tx.date, cfg.date_window_days)
        r = reference_score(inv.number, tx)
        warnings: list[str] = []
        kind, a_note = "SINGLE", ""
        same_cur = (inv.currency or "") == tx.currency
        if same_cur:
            a = amount_score(inv.remaining, tx.remaining, cfg.amount_tolerance_pct)
            if a == 1.0:
                a_note = "the transaction amount matches the invoice amount"
            elif a > 0:
                a_note = f"the amount is within the {cfg.amount_tolerance_pct:.0%} tolerance (difference {abs(inv.remaining - tx.remaining)})"
            elif tx.remaining < inv.remaining and v >= 0.6:
                kind = "PARTIAL"
                a = round(min(0.6, 0.6 * float(tx.remaining / inv.remaining)), 4)
                a_note = f"the transaction covers {float(tx.remaining / inv.remaining):.0%} of the remaining invoice amount (possible partial payment)"
                warnings.append("Partial payment: the invoice would remain partially reconciled.")
                singles_for_split.append((tx, v, d))
            elif v >= 0.6 and r >= 1:
                a_note = f"the amounts differ by {abs(inv.remaining - tx.remaining)} (fees, tax, refund or exchange differences?)"
                warnings.append("Amount differs from the invoice; investigate the discrepancy before confirming.")
            else:
                continue
        else:
            if abs(inv.remaining - tx.remaining) > CENT / 2:
                continue
            a = 0.0
            warnings.append(f"The amounts match numerically but the currencies differ ({inv.currency} vs {tx.currency}). "
                            "Verify whether the bank transaction represents a converted payment.")
            a_note = "the raw amounts match, but the currencies differ"
        score = round(wA * a + wV * v + wD * d + wR * r, 4)
        parts = {"amount": a, "vendor": v, "date": d, "reference": r, "days_from_invoice": days}
        if kind == "PARTIAL":
            score = min(score, round(cfg.high - 0.01, 4))
        if score < cfg.review and not (not same_cur and v >= 0.6):
            continue  # currency-mismatch candidates with a matching vendor are always surfaced for review
        status = "SUGGESTED" if (score >= cfg.high and kind == "SINGLE" and same_cur and not warnings) else "NEEDS_REVIEW"
        expl = _explain(kind, parts, inv.currency, [tx], days, a_note)
        if warnings:
            expl += " " + " ".join(warnings)
        alloc = min(tx.remaining, inv.remaining)
        out.append(Candidate(kind, [tx.id], [{"transaction_id": tx.id, "amount": format(alloc, "f")}], score, status, parts, expl, warnings))

    # split payments: 2-3 partial transactions that sum exactly to the remaining amount
    pool = sorted(singles_for_split, key=lambda x: -(x[1] + x[2]))[:12]
    for n in (2, 3):
        for combo in combinations(pool, n):
            total = sum((c[0].remaining for c in combo), Decimal(0))
            if abs(total - inv.remaining) > CENT / 2:
                continue
            v = sum(c[1] for c in combo) / n
            d = sum(c[2] for c in combo) / n
            r = max(reference_score(inv.number, c[0]) for c in combo)
            a = 1.0
            score = min(round(wA * a + wV * v + wD * d + wR * r, 4), round(cfg.high - 0.01, 4))
            if score < cfg.review:
                continue
            parts = {"amount": a, "vendor": round(v, 4), "date": round(d, 4), "reference": r, "days_from_invoice": None}
            days = min((c[0].date - inv.date).days for c in combo) if inv.date else None
            expl = _explain("SPLIT", parts, inv.currency, [c[0] for c in combo], days, "")
            out.append(Candidate("SPLIT", [c[0].id for c in combo],
                                 [{"transaction_id": c[0].id, "amount": format(c[0].remaining, "f")} for c in combo],
                                 score, "NEEDS_REVIEW", parts, expl, ["Split payment: please confirm all linked transactions belong to this invoice."]))
    out.sort(key=lambda c: (-c.score, len(c.tx_ids)))
    return out[:max_results]
