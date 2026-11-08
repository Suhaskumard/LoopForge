from lib.nested import flatten


def test_flat():
    assert flatten([1, 2]) == [1, 2]


def test_one_level():
    assert flatten([1, [2, 3]]) == [1, 2, 3]
