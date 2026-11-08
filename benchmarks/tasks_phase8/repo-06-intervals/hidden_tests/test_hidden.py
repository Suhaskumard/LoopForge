from lib.intervals import merge_intervals


def test_touching():
    assert merge_intervals([(1, 2), (2, 3)]) == [(1, 3)]


def test_unsorted():
    assert merge_intervals([(5, 6), (1, 2), (2, 4)]) == [(1, 4), (5, 6)]


def test_contained():
    assert merge_intervals([(1, 10), (2, 3)]) == [(1, 10)]


def test_no_mutation():
    data = [(3, 4), (1, 3)]
    merge_intervals(data)
    assert data == [(3, 4), (1, 3)]


def test_empty():
    assert merge_intervals([]) == []
