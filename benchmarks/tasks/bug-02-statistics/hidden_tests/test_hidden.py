import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.stats import average, median

c = TestClient(app)


def post(values):
    r = c.post("/stats", json={"values": values})
    assert r.status_code == 200, r.text
    return r.json()


def test_mean_is_not_truncated():
    assert post([1, 2])["average"] == 1.5
    assert average([1, 2, 2]) == pytest.approx(5 / 3)


def test_median_odd_and_even():
    assert median([3, 1, 2]) == 2
    assert median([4, 1, 3, 2]) == 2.5
    assert post([10, 20])["median"] == 15


def test_empty_list_is_handled():
    body = post([])
    assert body == {"count": 0, "average": None, "median": None}
    assert average([]) is None and median([]) is None


def test_single_value_and_negative():
    assert post([7])["average"] == 7 and post([7])["median"] == 7
    assert post([-1, -3])["average"] == -2


def test_input_is_not_mutated_and_floats_work():
    data = [3.5, 1.5, 2.5]
    median(data)
    assert data == [3.5, 1.5, 2.5]
    assert post(data)["average"] == pytest.approx(2.5)
