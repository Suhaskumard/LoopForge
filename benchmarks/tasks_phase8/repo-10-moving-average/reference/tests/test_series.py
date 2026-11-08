import pytest
from lib.series import moving_average


def test_bad_window():
    with pytest.raises(ValueError):
        moving_average([1], 2)


def test_window_zero():
    with pytest.raises(ValueError):
        moving_average([1], 0)
