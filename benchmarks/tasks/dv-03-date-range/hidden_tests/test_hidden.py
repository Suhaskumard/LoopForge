from datetime import date

import pytest

from app.validators import days_inclusive, parse_date_range


def test_valid_range_and_whitespace():
    assert parse_date_range(" 2024-01-01 ", "2024-01-31\n") == (date(2024, 1, 1), date(2024, 1, 31))


def test_same_day_is_allowed_and_counts_one():
    assert parse_date_range("2024-05-05", "2024-05-05") == (date(2024, 5, 5), date(2024, 5, 5))
    assert days_inclusive("2024-05-05", "2024-05-05") == 1


@pytest.mark.parametrize("bad", ["2023-02-30", "2023-13-01", "23-01-01", "2023-1-1", "2023/01/01", "", "tomorrow", "2023-02-29"])
def test_bad_dates_raise(bad):
    with pytest.raises(ValueError):
        parse_date_range(bad, "2030-01-01")
    with pytest.raises(ValueError):
        parse_date_range("2000-01-01", bad)


def test_end_before_start_raises():
    with pytest.raises(ValueError):
        parse_date_range("2024-01-02", "2024-01-01")


def test_leap_years():
    assert parse_date_range("2024-02-29", "2024-03-01")[0] == date(2024, 2, 29)
    assert days_inclusive("2024-02-28", "2024-03-01") == 3
    assert days_inclusive("2023-02-28", "2023-03-01") == 2
    assert days_inclusive("2023-01-01", "2023-12-31") == 365
    assert days_inclusive("2024-01-01", "2024-12-31") == 366
    with pytest.raises(ValueError):
        parse_date_range("1900-02-29", "1900-03-01")  # 1900 was not a leap year
    assert parse_date_range("2000-02-29", "2000-03-01")[0] == date(2000, 2, 29)  # 2000 was


def test_non_string_input_raises_value_error():
    with pytest.raises(ValueError):
        parse_date_range(None, "2024-01-01")
