import pytest
from lib.roman import roman_to_int


def test_subtractive():
    assert roman_to_int("IV") == 4
    assert roman_to_int("IX") == 9


def test_long():
    assert roman_to_int("MCMXCIV") == 1994


def test_xl():
    assert roman_to_int("XLII") == 42


def test_simple():
    assert roman_to_int("VIII") == 8


@pytest.mark.parametrize("bad", ["", "ABC", "iv"])
def test_invalid(bad):
    with pytest.raises(ValueError):
        roman_to_int(bad)
