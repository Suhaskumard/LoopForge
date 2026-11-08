from decimal import Decimal

import pytest

from app.validators import format_money, parse_money


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$1,234.50", "1234.50"),
        ("1234.5", "1234.50"),
        ("0.99", "0.99"),
        ("1,000", "1000.00"),
        ("$7", "7.00"),
        ("0", "0.00"),
        ("1000000000", "1000000000.00"),
        (" 12.30 ", "12.30"),
        ("999,999,999.99", "999999999.99"),
    ],
)
def test_parse_valid(text, expected):
    got = parse_money(text)
    assert isinstance(got, Decimal) and got == Decimal(expected) and str(got) == expected


@pytest.mark.parametrize("text", ["-5", "-0.01", "1.234", "1,23", "12,34,567", ",100", "", "abc", "$", "$$5", "1,000,000,000.01", "1000000000.01", "1.", ".5", "1e3", "NaN", "5 dollars"])
def test_parse_invalid(text):
    with pytest.raises(ValueError):
        parse_money(text)


def test_non_string_raises_value_error():
    with pytest.raises(ValueError):
        parse_money(12.5)


def test_format():
    assert format_money(Decimal("1234.5")) == "$1,234.50"
    assert format_money(Decimal("0")) == "$0.00"
    assert format_money(Decimal("1000000")) == "$1,000,000.00"
    assert format_money(Decimal("999.999")) == "$1,000.00"


@pytest.mark.parametrize("text", ["$1,234.50", "0.01", "999,999,999.99", "12"])
def test_round_trip(text):
    assert parse_money(format_money(parse_money(text))) == parse_money(text)
