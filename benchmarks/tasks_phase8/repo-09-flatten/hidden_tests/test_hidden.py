from lib.nested import flatten


def test_deep():
    assert flatten([1, [2, [3, [4]]]]) == [1, 2, 3, 4]


def test_tuples():
    assert flatten([(1, (2,)), 3]) == [1, 2, 3]


def test_strings_kept():
    assert flatten(["ab", ["cd"]]) == ["ab", "cd"]


def test_empty_nested():
    assert flatten([[], [[]]]) == []


def test_flat():
    assert flatten([1, 2]) == [1, 2]
