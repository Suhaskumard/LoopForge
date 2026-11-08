from lib.text import is_palindrome


def test_true():
    assert is_palindrome("abba")


def test_false():
    assert not is_palindrome("abc")
