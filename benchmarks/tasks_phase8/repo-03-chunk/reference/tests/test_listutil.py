from lib.listutil import chunk


def test_exact():
    assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_empty():
    assert chunk([], 3) == []
