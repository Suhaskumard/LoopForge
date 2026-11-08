import pytest

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
