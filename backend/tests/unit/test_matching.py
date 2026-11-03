from datetime import date
from decimal import Decimal

from app.services.matching import (InvoiceView, MatchConfig, TxView, amount_score, date_score, reference_score,
                                   score_candidates, vendor_score)

CFG = MatchConfig()


def inv(**kw):
    d = dict(id="i1", vendor_norm="abc office supplies", number="INV-2026-1042", date=date(2026, 10, 12), due_date=None,
             currency="INR", remaining=Decimal("5800"))
    d.update(kw)
    return InvoiceView(**d)


def tx(id="t1", d=date(2026, 10, 13), desc="abc office supplies", raw="UPI/ABC OFFICE SUPPLIES", ref=None, cur="INR", rem="5800"):
    return TxView(id, d, desc, raw, ref, cur, Decimal(rem))


def test_amount_score():
    assert amount_score(Decimal("5800"), Decimal("5800"), 0.02) == 1.0
    assert 0.5 <= amount_score(Decimal("5800"), Decimal("5750"), 0.02) < 1.0
    assert amount_score(Decimal("5800"), Decimal("5000"), 0.02) == 0.0


def test_vendor_and_reference_scores():
    assert vendor_score("abc office supplies", "abc office supplies") == 1.0
    assert vendor_score("abc office supplies", "zeta travel") < 0.4
    assert vendor_score("", "x") == 0.0
    assert reference_score("INV-2026-1042", tx(raw="PAY INV20261042")) == 1.0
    assert reference_score("12", tx(raw="12")) == 0.0  # too short to be a reliable reference


def test_date_score_window():
    i = inv()
    assert date_score(i, date(2026, 10, 13), 30)[0] == 1.0
    assert date_score(i, date(2026, 10, 18), 30)[0] == 0.9  # example B: 6 days apart, reduced but not rejected
    assert date_score(i, date(2027, 1, 1), 30)[0] == 0.0


def test_example_a_exact_match_is_high_confidence():
    c = score_candidates(inv(), [tx()], CFG)[0]
    assert c.status == "SUGGESTED" and c.score >= CFG.high and c.kind == "SINGLE"
    assert "amount matches" in c.explanation and "vendor" in c.explanation


def test_example_b_date_difference_lowers_score_but_keeps_candidate():
    a = score_candidates(inv(), [tx()], CFG)[0].score
    b = score_candidates(inv(), [tx(d=date(2026, 10, 18))], CFG)[0].score
    assert 0 < a - b < 0.1


def test_reference_adds_score():
    base = score_candidates(inv(), [tx()], CFG)[0].score
    with_ref = score_candidates(inv(), [tx(raw="UPI/ABC OFFICE SUPPLIES/INV-2026-1042")], CFG)[0].score
    assert with_ref > base


def test_example_c_split_payment_suggested():
    i = inv(vendor_norm="sharma electricals", remaining=Decimal("10000"), number=None)
    txs = [tx("a", date(2026, 10, 9), "sharma electricals", "NEFT SHARMA ELECTRICALS", rem="6000"),
           tx("b", date(2026, 10, 12), "sharma electricals", "NEFT SHARMA ELECTRICALS", rem="4000")]
    res = score_candidates(i, txs, CFG)
    split = next(c for c in res if c.kind == "SPLIT")
    assert sorted(split.tx_ids) == ["a", "b"] and split.status == "NEEDS_REVIEW"
    assert sum(Decimal(p["amount"]) for p in split.plan) == Decimal("10000")
    assert any(c.kind == "PARTIAL" for c in res)  # each part alone is a partial-payment candidate


def test_currency_mismatch_never_gets_a_perfect_amount_score():
    c = score_candidates(inv(), [tx(cur="USD")], CFG)
    assert c and c[0].signals["amount"] == 0.0 and c[0].status == "NEEDS_REVIEW"
    assert "currencies differ" in c[0].explanation
    assert score_candidates(inv(), [tx(cur="USD", rem="100")], CFG) == []


def test_unrelated_transaction_is_not_suggested():
    assert score_candidates(inv(), [tx(desc="zeta travel", raw="ZETA TRAVEL", rem="1234.56")], CFG) == []


def test_already_allocated_transaction_is_skipped():
    assert score_candidates(inv(), [tx(rem="0")], CFG) == []


def test_amount_discrepancy_with_matching_reference_is_flagged_for_review():
    c = score_candidates(inv(), [tx(raw="ABC OFFICE SUPPLIES INV-2026-1042", rem="6100")], CFG)
    assert c and c[0].status == "NEEDS_REVIEW" and "differ" in c[0].explanation


def test_competing_invoices_rank_by_score():
    res = score_candidates(inv(), [tx("good"), tx("meh", d=date(2026, 12, 1), desc="abc office", raw="ABC OFFICE")], CFG)
    assert res[0].tx_ids == ["good"]
