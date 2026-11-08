from lib.slugify import slugify


def test_simple():
    assert slugify("hello") == "hello"


def test_space():
    assert slugify("a b") == "a-b"
