import pytest

from app.validators import is_valid_isbn13


@pytest.mark.parametrize("v", ["9780441172719", "978-0-441-17271-9", "978 0 441 17271 9", "9780306406157", "9791090636071"])
def test_valid(v):
    assert is_valid_isbn13(v) is True


@pytest.mark.parametrize("v", ["9780441172718", "978044117271", "97804411727190", "", "abcdefghijklm", "978-0-441-17271-X", "      ", "9780441172719\n9"])
def test_invalid(v):
    assert is_valid_isbn13(v) is False


def test_non_strings_return_false_instead_of_raising():
    assert is_valid_isbn13(None) is False
    assert is_valid_isbn13(9780441172719) is False


def test_checksum_uses_alternating_weights_including_check_digit():
    # same digits, one transposition of adjacent unequal digits must break the checksum
    assert is_valid_isbn13("9780441172719") and not is_valid_isbn13("9780441172179")
