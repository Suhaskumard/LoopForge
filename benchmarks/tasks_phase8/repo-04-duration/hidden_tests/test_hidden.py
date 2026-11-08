import pytest
from lib.duration import parse_duration


def test_hours_minutes():
    assert parse_duration("1h30m") == 5400


def test_all_parts():
    assert parse_duration("1h2m3s") == 3723


def test_hours_only():
    assert parse_duration("2h") == 7200


def test_minutes_seconds():
    assert parse_duration("5m10s") == 310


@pytest.mark.parametrize("bad", ["", "abc", "1x", "30m1h"])
def test_invalid(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)
