import pytest
from lib.stats import median


def test_odd():
    assert median([3, 1, 2]) == 2


def test_empty():
    with pytest.raises(ValueError):
        median([])
