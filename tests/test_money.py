from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from mywealth import money
from mywealth.errors import ValidationError


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1234.56", 123456),
        ("1234,56", 123456),
        ("1.234,56", 123456),
        ("1,234.56", 123456),
        ("1.234", 123400),  # Italian thousands separator
        ("1.000.000", 100000000),
        ("1.000.000,5", 100000050),
        ("12", 1200),
        ("12.345", 1234500),
        ("0,5", 50),
        (" 1 234,50 € ", 123450),
        (7, 700),
    ],
)
def test_parse_amount_eur(text, expected):
    assert money.parse_amount(text, "EUR") == expected


def test_parse_amount_zero_decimals():
    assert money.parse_amount("1.500", "JPY") == 1500
    assert money.parse_amount("1500", "JPY") == 1500
    with pytest.raises(ValidationError):
        money.parse_amount("15,5", "JPY")


@pytest.mark.parametrize("text", ["", None, "abc", "1,2,3", "1.23.4", "1.2345", "1e5", "--1", True])
def test_parse_amount_invalid(text):
    with pytest.raises(ValidationError):
        money.parse_amount(text, "EUR")


def test_parse_amount_sign_rules():
    with pytest.raises(ValidationError):
        money.parse_amount("-5", "EUR")
    with pytest.raises(ValidationError):
        money.parse_amount("0", "EUR")
    assert money.parse_amount("-5", "EUR", allow_negative=True) == -500
    assert money.parse_amount("0", "EUR", allow_zero=True) == 0


def test_minor_roundtrip():
    assert money.from_minor(123456, "EUR") == Decimal("1234.56")
    assert money.from_minor(1500, "JPY") == Decimal("1500")
    assert money.to_minor(Decimal("1.005"), "EUR") == 101  # half up
    assert money.fmt(-5, "EUR") == "-0.05"
    assert money.fmt(1500, "JPY") == "1500"
    assert money.fmt(None, "EUR") is None


def test_parse_decimal_rates():
    assert money.parse_decimal("0,9512") == Decimal("0.9512")
    assert money.parse_decimal("1.0734") == Decimal("1.0734")


def test_parse_date():
    assert money.parse_date("2026-03-05") == date(2026, 3, 5)
    assert money.parse_date("05/03/2026") == date(2026, 3, 5)
    with pytest.raises(ValidationError):
        money.parse_date("2026-13-01")


def test_check_currency():
    assert money.check_currency(" chf ") == "CHF"
    with pytest.raises(ValidationError):
        money.check_currency("XXX")
