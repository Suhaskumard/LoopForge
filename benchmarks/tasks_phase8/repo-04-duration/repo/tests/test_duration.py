from lib.duration import parse_duration


def test_seconds():
    assert parse_duration("45s") == 45


def test_minutes():
    assert parse_duration("2m") == 120
