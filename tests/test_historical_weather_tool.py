from datetime import date, timedelta

import pytest

from agent.tools.weather_service import _validate_historical_dates


def test_valid_historical_date_range():
    start, end = _validate_historical_dates("2025-01-01", "2025-12-31")

    assert start == date(2025, 1, 1)
    assert end == date(2025, 12, 31)


def test_leap_year_date_range_is_valid():
    start, end = _validate_historical_dates("2024-01-01", "2024-12-31")

    assert (end - start).days + 1 == 366


def test_start_date_after_end_date_is_rejected():
    with pytest.raises(ValueError, match="start_date"):
        _validate_historical_dates("2025-12-31", "2025-01-01")


def test_future_date_is_rejected():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    with pytest.raises(ValueError, match="before today"):
        _validate_historical_dates(tomorrow, tomorrow)


def test_today_is_rejected_as_historical_end_date():
    today = date.today().isoformat()

    with pytest.raises(ValueError, match="before today"):
        _validate_historical_dates(today, today)


def test_date_range_over_366_days_is_rejected():
    with pytest.raises(ValueError, match="366 days"):
        _validate_historical_dates("2024-01-01", "2025-01-01")


def test_invalid_date_format_is_rejected():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _validate_historical_dates("01-01-2025", "2025-01-05")
