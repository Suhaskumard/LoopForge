from lib.roman import roman_to_int


def test_simple():
    assert roman_to_int("VIII") == 8


def test_thousand():
    assert roman_to_int("MM") == 2000
