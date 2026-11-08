import pytest
from lib.stats import median


def test_even():
    assert median([1, 2, 3, 4]) == 2.5


def test_even_unsorted():
    assert median([10, 2, 4, 8]) == 6


def test_odd():
    assert median([5, 1, 3]) == 3


def test_single():
    assert median([7]) == 7


def test_empty():
    with pytest.raises(ValueError):
        median([])
