from lib.intervals import merge_intervals


def test_overlap():
    assert merge_intervals([(1, 5), (3, 7)]) == [(1, 7)]


def test_disjoint():
    assert merge_intervals([(1, 2), (4, 5)]) == [(1, 2), (4, 5)]
