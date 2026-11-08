from lib.slugify import slugify


def test_punctuation():
    assert slugify("Hello,   World!") == "hello-world"


def test_edges():
    assert slugify("  --Hi--  ") == "hi"


def test_digits():
    assert slugify("Python 3.12") == "python-3-12"


def test_empty():
    assert slugify("!!!") == ""


def test_plain():
    assert slugify("abc") == "abc"
