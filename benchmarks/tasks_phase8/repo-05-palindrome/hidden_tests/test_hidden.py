from lib.text import is_palindrome


def test_sentence():
    assert is_palindrome("A man, a plan, a canal: Panama")


def test_case():
    assert is_palindrome("Racecar")


def test_not():
    assert not is_palindrome("hello, world")


def test_empty():
    assert is_palindrome("")


def test_digits():
    assert is_palindrome("12 21")
