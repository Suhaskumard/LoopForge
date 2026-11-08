import pytest

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
