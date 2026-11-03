from datetime import date
from decimal import Decimal

import pytest

from app.processors.normalize import (alnum, detect_currency, detect_decimal_style, normalize_vendor, parse_amount,
                                      parse_date, quantize_money)


@pytest.mark.parametrize("raw,expected", [
    ("1,234.56", "1234.56"), ("1.234,56", "1234.56"), ("1 234,56", "1234.56"), ("12,34", "12.34"),
    ("1,00,000.00", "100000.00"), ("₹5,800.00", "5800.00"), ("(12.00)", "-12.00"), ("1'234.50", "1234.50"), ("5800", "5800"),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == Decimal(expected)


def test_parse_amount_uses_decimal_hint():
    assert parse_amount("1.234", ",") == Decimal("1234")
    assert parse_amount("1,234", ".") == Decimal("1234")
    assert parse_amount("1,234", ",") == Decimal("1.234")


def test_parse_amount_garbage():
    assert parse_amount("abc") is None and parse_amount(None) is None and parse_amount("") is None


def test_detect_decimal_style():
    assert detect_decimal_style(["1.234,56", "10,00"]) == ","
    assert detect_decimal_style(["1,234.56", "10.00"]) == "."
    assert detect_decimal_style([]) is None


@pytest.mark.parametrize("text,expected,ambiguous", [
    ("2026-10-12", date(2026, 10, 12), False), ("12 Oct 2026", date(2026, 10, 12), False),
    ("October 12, 2026", date(2026, 10, 12), False), ("13/10/2026", date(2026, 10, 13), False),
    ("10/13/2026", date(2026, 10, 13), False), ("12.10.2026", date(2026, 10, 12), False),
    ("05/10/2026", date(2026, 10, 5), True), ("12. März 2026", date(2026, 3, 12), False),
    ("12 octobre 2026", date(2026, 10, 12), False), ("31/02/2026", None, False),
])
def test_parse_date(text, expected, ambiguous):
    assert parse_date(text) == (expected, ambiguous)


def test_parse_date_preference():
    assert parse_date("05/10/2026", "MDY") == (date(2026, 5, 10), True)


def test_currency_detection():
    assert detect_currency("Total ₹ 5,800") == ("INR", False)
    assert detect_currency("Total INR 5,800") == ("INR", False)
    assert detect_currency("Total $ 5") == ("USD", True)  # bare dollar sign is ambiguous
    assert detect_currency("USD 10 and EUR 5")[1] is True
    assert detect_currency("nothing here") == (None, False)


def test_vendor_normalization():
    assert normalize_vendor("ABC Office Supplies Pvt. Ltd.") == "abc office supplies"
    assert normalize_vendor("UPI/ABC OFFICE SUPPLIES/TXN893021", bank_description=True) == "abc office supplies"
    assert alnum("INV-2026/1042") == "inv20261042"


def test_quantize_by_currency():
    assert quantize_money(Decimal("10.005"), "INR") == Decimal("10.01")
    assert quantize_money(Decimal("1000.4"), "JPY") == Decimal("1000")
