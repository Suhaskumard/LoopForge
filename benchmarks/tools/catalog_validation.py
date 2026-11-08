"""Data-validation tasks: pure functions in `app/validators.py` (plus a minimal FastAPI app).

Boundary cases are the point: a model that writes plausible-looking code still fails the hidden
edge cases (checksums, separators, ranges, rounding).
"""

from typing import Any

MAIN = 'from fastapi import FastAPI\n\napp = FastAPI()\n'
TAIL = "\nThe project must also contain `app/main.py` defining a FastAPI `app` (entry point `app.main:app`) (no endpoints required) and `app/__init__.py`. Include unit tests (pytest)."


def _task(id_: str, difficulty: str, req: str, criteria: list[str], validators: str, test: str) -> dict[str, Any]:
    return {
        "id": id_,
        "category": "data_validation",
        "difficulty": difficulty,
        "requirement": req + TAIL,
        "acceptance_criteria": criteria,
        "reference": {"app/__init__.py": "", "app/main.py": MAIN, "app/validators.py": validators},
        "hidden_test": test,
        "seed": None,
    }


def tasks() -> list[dict[str, Any]]:
    return [
        _task(
            "dv-01-isbn13",
            "medium",
            "Create `app/validators.py` with `is_valid_isbn13(value: str) -> bool`. Hyphens and spaces are ignored. "
            "A valid ISBN-13 has exactly 13 digits after cleaning and a correct checksum: the weighted sum of the digits "
            "(weights alternate 1,3,1,3,... from the left, including the check digit) must be divisible by 10. "
            "Anything else (letters, wrong length, empty string, bad checksum) returns False and must never raise.",
            ["Valid ISBN-13 values are accepted with or without hyphens/spaces", "Bad checksums and malformed input return False without raising"],
            '''import re


def is_valid_isbn13(value: str) -> bool:
    if not isinstance(value, str):
        return False
    digits = re.sub(r"[-\\s]", "", value)
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits))
    return total % 10 == 0
''',
            '''import pytest

from app.validators import is_valid_isbn13


@pytest.mark.parametrize("v", ["9780441172719", "978-0-441-17271-9", "978 0 441 17271 9", "9780306406157", "9791090636071"])
def test_valid(v):
    assert is_valid_isbn13(v) is True


@pytest.mark.parametrize("v", ["9780441172718", "978044117271", "97804411727190", "", "abcdefghijklm", "978-0-441-17271-X", "      ", "9780441172719\\n9"])
def test_invalid(v):
    assert is_valid_isbn13(v) is False


def test_non_strings_return_false_instead_of_raising():
    assert is_valid_isbn13(None) is False
    assert is_valid_isbn13(9780441172719) is False


def test_checksum_uses_alternating_weights_including_check_digit():
    # same digits, one transposition of adjacent unequal digits must break the checksum
    assert is_valid_isbn13("9780441172719") and not is_valid_isbn13("9780441172179")
''',
        ),
        _task(
            "dv-02-luhn",
            "medium",
            "Create `app/validators.py` with `luhn_valid(number: str) -> bool` for payment card numbers. Spaces and dashes are "
            "ignored. After cleaning, the number must be 12 to 19 digits long and satisfy the Luhn checksum (from the right, "
            "double every second digit, subtract 9 from results above 9, total divisible by 10). Anything else returns False; "
            "it must never raise. Also provide `mask_card(number: str) -> str` returning only the last 4 digits prefixed by "
            "asterisks to the original cleaned length (e.g. `************1111`), and raising `ValueError` if the number is not "
            "Luhn-valid.",
            ["Luhn checksum and length rules are enforced", "Masking reveals only the last four digits and rejects invalid numbers"],
            '''import re


def _clean(number: str) -> str:
    return re.sub(r"[ -]", "", number) if isinstance(number, str) else ""


def luhn_valid(number: str) -> bool:
    digits = _clean(number)
    if not digits.isdigit() or not 12 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def mask_card(number: str) -> str:
    if not luhn_valid(number):
        raise ValueError("invalid card number")
    digits = _clean(number)
    return "*" * (len(digits) - 4) + digits[-4:]
''',
            '''import pytest

from app.validators import luhn_valid, mask_card

GOOD = ["4111111111111111", "4111 1111 1111 1111", "4111-1111-1111-1111", "5500005555555559", "378282246310005", "6011111111111117", "4012888888881881"]


@pytest.mark.parametrize("n", GOOD)
def test_valid_numbers(n):
    assert luhn_valid(n) is True


@pytest.mark.parametrize("n", ["4111111111111112", "411111111111", "41111111111111111111", "", "abcd efgh ijkl mnop", "4111_1111_1111_1111", "0000000000000001"])
def test_invalid_numbers(n):
    assert luhn_valid(n) is False


def test_length_boundaries():
    assert luhn_valid("000000000000") is True  # 12 digits, checksum 0
    assert luhn_valid("00000000000") is False  # 11 digits
    assert luhn_valid("0000000000000000000") is True  # 19 digits
    assert luhn_valid("00000000000000000000") is False  # 20 digits


def test_non_strings_do_not_raise():
    assert luhn_valid(None) is False
    assert luhn_valid(4111111111111111) is False


def test_mask_card():
    assert mask_card("4111 1111 1111 1111") == "************1111"
    assert mask_card("378282246310005") == "***********0005"


def test_mask_rejects_invalid():
    with pytest.raises(ValueError):
        mask_card("4111111111111112")
''',
        ),
        _task(
            "dv-03-date-range",
            "medium",
            "Create `app/validators.py` with `parse_date_range(start: str, end: str) -> tuple[date, date]` (`datetime.date`). "
            "Both arguments are ISO calendar dates `YYYY-MM-DD` (surrounding whitespace is ignored). Raise `ValueError` if either "
            "is not a real calendar date (e.g. `2023-02-30`, `2023-13-01`, `23-01-01`, `2023-1-1`) or if `end` is before `start`. "
            "`start == end` is allowed. Also provide `days_inclusive(start: str, end: str) -> int` returning the number of days "
            "in the range counting both ends (same day -> 1). Leap years must be handled correctly.",
            ["Only real ISO calendar dates are accepted", "end before start is rejected; equal dates allowed", "Inclusive day count is correct across leap years"],
            '''import re
from datetime import date

_ISO = re.compile(r"^\\d{4}-\\d{2}-\\d{2}$")


def _parse(value: str) -> date:
    text = value.strip() if isinstance(value, str) else ""
    if not _ISO.match(text):
        raise ValueError(f"not an ISO date: {value!r}")
    return date.fromisoformat(text)


def parse_date_range(start: str, end: str) -> tuple[date, date]:
    s, e = _parse(start), _parse(end)
    if e < s:
        raise ValueError("end is before start")
    return s, e


def days_inclusive(start: str, end: str) -> int:
    s, e = parse_date_range(start, end)
    return (e - s).days + 1
''',
            '''from datetime import date

import pytest

from app.validators import days_inclusive, parse_date_range


def test_valid_range_and_whitespace():
    assert parse_date_range(" 2024-01-01 ", "2024-01-31\\n") == (date(2024, 1, 1), date(2024, 1, 31))


def test_same_day_is_allowed_and_counts_one():
    assert parse_date_range("2024-05-05", "2024-05-05") == (date(2024, 5, 5), date(2024, 5, 5))
    assert days_inclusive("2024-05-05", "2024-05-05") == 1


@pytest.mark.parametrize("bad", ["2023-02-30", "2023-13-01", "23-01-01", "2023-1-1", "2023/01/01", "", "tomorrow", "2023-02-29"])
def test_bad_dates_raise(bad):
    with pytest.raises(ValueError):
        parse_date_range(bad, "2030-01-01")
    with pytest.raises(ValueError):
        parse_date_range("2000-01-01", bad)


def test_end_before_start_raises():
    with pytest.raises(ValueError):
        parse_date_range("2024-01-02", "2024-01-01")


def test_leap_years():
    assert parse_date_range("2024-02-29", "2024-03-01")[0] == date(2024, 2, 29)
    assert days_inclusive("2024-02-28", "2024-03-01") == 3
    assert days_inclusive("2023-02-28", "2023-03-01") == 2
    assert days_inclusive("2023-01-01", "2023-12-31") == 365
    assert days_inclusive("2024-01-01", "2024-12-31") == 366
    with pytest.raises(ValueError):
        parse_date_range("1900-02-29", "1900-03-01")  # 1900 was not a leap year
    assert parse_date_range("2000-02-29", "2000-03-01")[0] == date(2000, 2, 29)  # 2000 was


def test_non_string_input_raises_value_error():
    with pytest.raises(ValueError):
        parse_date_range(None, "2024-01-01")
''',
        ),
        _task(
            "dv-04-phone",
            "hard",
            "Create `app/validators.py` with `normalize_phone(raw: str, default_country_code: str = \"1\") -> str` returning "
            "an E.164 string like `+14155552671`, or raising `ValueError`. Rules: ignore spaces, dots, dashes and parentheses; "
            "a number starting with `+` is international: it must be followed by 8 to 14 digits and the first digit may not be 0; "
            "a number starting with `00` is treated like `+` (the `00` removed); otherwise it is national: a leading single `0` "
            "trunk digit is dropped and `default_country_code` is prepended, and the national part must be exactly 10 digits "
            "when the default country code is `1` (and 6 to 12 digits for any other default). Any letter or other character "
            "(besides the ignorable separators and a leading `+`) raises ValueError, as does an empty string.",
            ["International, 00-prefixed and national numbers normalise to E.164", "Invalid characters, lengths and leading zeros raise ValueError"],
            '''import re


def normalize_phone(raw: str, default_country_code: str = "1") -> str:
    if not isinstance(raw, str):
        raise ValueError("phone must be a string")
    text = raw.strip()
    if not text:
        raise ValueError("empty")
    plus = text.startswith("+")
    body = re.sub(r"[ .\\-()]", "", text[1:] if plus else text)
    if not body.isdigit():
        raise ValueError("invalid characters")
    if plus or body.startswith("00"):
        digits = body if plus else body[2:]
        if not 8 <= len(digits) <= 14 or digits.startswith("0"):
            raise ValueError("invalid international number")
        return "+" + digits
    national = body[1:] if body.startswith("0") else body
    if default_country_code == "1":
        if len(national) != 10:
            raise ValueError("national number must have 10 digits")
    elif not 6 <= len(national) <= 12:
        raise ValueError("bad national length")
    return "+" + default_country_code + national
''',
            '''import pytest

from app.validators import normalize_phone


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+14155552671", "+14155552671"),
        ("(415) 555-2671", "+14155552671"),
        ("415.555.2671", "+14155552671"),
        ("0415 555 2671", "+14155552671"),
        ("+44 20 7946 0958", "+442079460958"),
        ("0044 20 7946 0958", "+442079460958"),
        ("  +1 (415) 555-2671  ", "+14155552671"),
    ],
)
def test_normalises(raw, expected):
    assert normalize_phone(raw) == expected


def test_other_default_country():
    assert normalize_phone("020 7946 0958", default_country_code="44") == "+442079460958"
    assert normalize_phone("7946 0958", default_country_code="44") == "+4479460958"


@pytest.mark.parametrize("bad", ["", "   ", "abc", "415-555-CALL", "+0123456789", "+1234567", "+123456789012345", "415555267", "41555526711", "+44 20 7946 09x8", "++14155552671", "415-555-2671 ext 5"])
def test_invalid(bad):
    with pytest.raises(ValueError):
        normalize_phone(bad)


def test_non_string():
    with pytest.raises(ValueError):
        normalize_phone(4155552671)


def test_international_length_boundaries():
    assert normalize_phone("+12345678") == "+12345678"
    assert normalize_phone("+12345678901234") == "+12345678901234"
    with pytest.raises(ValueError):
        normalize_phone("+1234567")
    with pytest.raises(ValueError):
        normalize_phone("+123456789012345")
''',
        ),
        _task(
            "dv-05-password-strength",
            "easy",
            "Create `app/validators.py` with `check_password(password: str, username: str = \"\") -> list[str]` returning the list "
            "of violated rule codes in this fixed order (empty list = acceptable): `too_short` (fewer than 12 characters), "
            "`no_upper`, `no_lower`, `no_digit`, `no_symbol` (no character that is not a letter or digit), `has_space` "
            "(contains whitespace), `contains_username` (username is non-empty and appears in the password, case-insensitively), "
            "`common` (the password, lower-cased, is one of: password, 123456789012, qwertyuiop12, letmein12345).",
            ["Every violated rule is reported once, in the specified order", "Acceptable passwords return an empty list"],
            '''COMMON = {"password", "123456789012", "qwertyuiop12", "letmein12345"}


def check_password(password: str, username: str = "") -> list[str]:
    out: list[str] = []
    if len(password) < 12:
        out.append("too_short")
    if not any(c.isupper() for c in password):
        out.append("no_upper")
    if not any(c.islower() for c in password):
        out.append("no_lower")
    if not any(c.isdigit() for c in password):
        out.append("no_digit")
    if all(c.isalnum() for c in password):
        out.append("no_symbol")
    if any(c.isspace() for c in password):
        out.append("has_space")
    if username and username.lower() in password.lower():
        out.append("contains_username")
    if password.lower() in COMMON:
        out.append("common")
    return out
''',
            '''import pytest

from app.validators import check_password


def test_strong_password_has_no_violations():
    assert check_password("Tr0ub4dor&3xyz") == []


def test_order_is_fixed_and_every_rule_reported():
    assert check_password("abc") == ["too_short", "no_upper", "no_digit", "no_symbol"]
    assert check_password("ABC") == ["too_short", "no_lower", "no_digit", "no_symbol"]


def test_exactly_twelve_characters_is_long_enough():
    assert "too_short" not in check_password("Abcdefgh12!x")
    assert "too_short" in check_password("Abcdefgh12!")


def test_space_is_flagged_and_counts_as_a_non_alphanumeric_symbol():
    # a space is not a letter or digit, so it satisfies "symbol" but is still flagged
    assert check_password("Correct Horse 9") == ["has_space"]


def test_username_check_is_case_insensitive_and_skipped_when_empty():
    assert "contains_username" in check_password("xxALICExx12!Ab", username="alice")
    assert "contains_username" not in check_password("xxALICExx12!Ab", username="")
    assert "contains_username" not in check_password("xxBOBxx12!Abcd", username="alice")


@pytest.mark.parametrize("pw", ["PASSWORD", "Password", "123456789012", "QWERTYUIOP12", "LetMeIn12345"])
def test_common_passwords(pw):
    assert "common" in check_password(pw)


def test_symbols_are_non_alphanumeric_characters():
    assert "no_symbol" in check_password("Abcdefghij12")
    assert "no_symbol" not in check_password("Abcdefghij1_")
    assert "no_symbol" not in check_password("Abcdefghij1!")
''',
        ),
        _task(
            "dv-06-money",
            "hard",
            "Create `app/validators.py` with `parse_money(text: str) -> decimal.Decimal`. Accepts an optional leading `$`, optional "
            "thousands separators (commas) and an optional fractional part with at most 2 digits: `$1,234.50`, `1234.5`, `0.99`, "
            "`1,000`. Returns an exact `Decimal` quantized to 2 decimal places (`Decimal('1234.50')`). Reject with `ValueError`: "
            "negative amounts, more than 2 decimal places, misplaced commas (`1,23`, `12,34,567`, `,100`), an empty string, "
            "letters, a bare `$`, and amounts above 1,000,000,000.00. Also provide `format_money(amount: Decimal) -> str` "
            "returning `$1,234.50` style text (always 2 decimals, commas every three digits).",
            ["Valid amounts parse to exact two-decimal Decimals", "Malformed, negative, over-precise and oversized amounts raise ValueError", "format_money round-trips with parse_money"],
            '''import re
from decimal import Decimal

_PATTERN = re.compile(r"^\\$?(\\d{1,3}(,\\d{3})+|\\d+)(\\.\\d{1,2})?$")
_MAX = Decimal("1000000000.00")


def parse_money(text: str) -> Decimal:
    if not isinstance(text, str) or not _PATTERN.match(text.strip()):
        raise ValueError(f"invalid amount: {text!r}")
    amount = Decimal(text.strip().lstrip("$").replace(",", "")).quantize(Decimal("0.01"))
    if amount > _MAX:
        raise ValueError("amount too large")
    return amount


def format_money(amount: Decimal) -> str:
    return "$" + f"{Decimal(amount).quantize(Decimal('0.01')):,.2f}"
''',
            '''from decimal import Decimal

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
''',
        ),
    ]
