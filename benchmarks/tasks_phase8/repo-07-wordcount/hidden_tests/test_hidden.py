from lib.words import word_count


def test_punctuation():
    assert word_count("Hi, hi! HI?") == {"hi": 3}


def test_apostrophe():
    assert word_count("don't stop") == {"don't": 1, "stop": 1}


def test_digits():
    assert word_count("r2d2 r2d2") == {"r2d2": 2}


def test_separators():
    assert word_count("a-b;c") == {"a": 1, "b": 1, "c": 1}


def test_basic():
    assert word_count("a b a") == {"a": 2, "b": 1}
