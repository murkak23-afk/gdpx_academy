from datetime import timezone

from src.services.admin_stats_service import AdminStatsService


def test_period_bounds_day_starts_at_utc_midnight() -> None:
    start, end = AdminStatsService.period_bounds("day")
    assert start.tzinfo == timezone.utc
    assert end.tzinfo == timezone.utc
    assert start <= end
    assert start.hour == 0
    assert start.minute == 0
    assert start.second == 0
    assert start.microsecond == 0


def test_period_bounds_week_is_about_seven_days() -> None:
    start, end = AdminStatsService.period_bounds("week")
    delta = end - start
    assert delta.total_seconds() >= 7 * 24 * 3600 - 5
    assert delta.total_seconds() <= 7 * 24 * 3600 + 5


def test_period_bounds_month_is_about_thirty_days() -> None:
    start, end = AdminStatsService.period_bounds("month")
    delta = end - start
    assert delta.total_seconds() >= 30 * 24 * 3600 - 5
    assert delta.total_seconds() <= 30 * 24 * 3600 + 5


def test_period_bounds_unknown_defaults_to_week() -> None:
    start, end = AdminStatsService.period_bounds("unknown")
    delta = end - start
    assert delta.total_seconds() >= 7 * 24 * 3600 - 5
    assert delta.total_seconds() <= 7 * 24 * 3600 + 5
