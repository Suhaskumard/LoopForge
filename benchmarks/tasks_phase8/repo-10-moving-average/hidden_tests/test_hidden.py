import pytest
from lib.series import moving_average


def test_basic():
    assert moving_average([1, 2, 3, 4], 2) == [1.5, 2.5, 3.5]


def test_full_window():
    assert moving_average([2, 4, 6], 3) == [4]


def test_window_one():
    assert moving_average([5, 6], 1) == [5, 6]


def test_bad_window():
    with pytest.raises(ValueError):
        moving_average([1, 2], 3)


def test_zero_window():
    with pytest.raises(ValueError):
        moving_average([1, 2], 0)
