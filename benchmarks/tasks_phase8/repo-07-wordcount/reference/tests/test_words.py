from lib.words import word_count


def test_basic():
    assert word_count("a b a") == {"a": 2, "b": 1}


def test_empty():
    assert word_count("") == {}
