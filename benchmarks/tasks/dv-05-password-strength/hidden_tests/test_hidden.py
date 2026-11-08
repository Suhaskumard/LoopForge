import pytest

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
