"""Scheduling behaviour: wall-clock times honour the configured timezone."""

from datetime import datetime, timezone

import pytest

from src.infrastructure.scheduler.job_scheduler import (
    ScheduleType,
    compute_next_cron_run,
    resolve_timezone,
)

JAKARTA = "Asia/Jakarta"


def test_clock_time_is_interpreted_in_the_configured_timezone():
    """`/remind 18:00` fires at 18:00 local, not 18:00 UTC."""
    base = datetime(2026, 3, 1, 6, 0, tzinfo=timezone.utc)  # 13:00 in Jakarta

    kind, next_run, _ = _parse("18:00", base, JAKARTA)

    assert kind is ScheduleType.ONCE
    assert next_run.tzinfo is timezone.utc
    assert next_run == datetime(2026, 3, 1, 11, 0, tzinfo=timezone.utc)


def test_clock_time_already_passed_today_rolls_to_tomorrow():
    base = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)  # 19:00 in Jakarta

    _, next_run, _ = _parse("18:00", base, JAKARTA)

    assert next_run == datetime(2026, 3, 2, 11, 0, tzinfo=timezone.utc)


def test_relative_durations_are_timezone_independent():
    base = datetime(2026, 3, 1, 6, 0, tzinfo=timezone.utc)

    _, next_run, _ = _parse("10m", base, JAKARTA)

    assert next_run == datetime(2026, 3, 1, 6, 10, tzinfo=timezone.utc)


def test_cron_fields_are_wall_clock_in_the_configured_timezone():
    """`0 9 * * *` means 09:00 Jakarta, i.e. 02:00 UTC."""
    base = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)

    next_run = compute_next_cron_run("0 9 * * *", base, tz=JAKARTA)

    assert next_run == datetime(2026, 3, 1, 2, 0, tzinfo=timezone.utc)


def test_cron_defaults_to_utc_when_no_timezone_given():
    base = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)

    assert compute_next_cron_run("0 9 * * *", base) == datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)


def test_unknown_timezone_falls_back_to_utc_instead_of_crashing():
    assert resolve_timezone("Mars/Olympus_Mons") is timezone.utc
    assert resolve_timezone("") is timezone.utc


def test_naive_iso_timestamp_is_read_as_local_time():
    base = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)

    _, next_run, _ = _parse("2026-03-05 18:00", base, JAKARTA)

    assert next_run == datetime(2026, 3, 5, 11, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("bad", ["25:00", "18:99"])
def test_impossible_clock_times_are_rejected(bad):
    base = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        _parse(bad, base, JAKARTA)


def _parse(expr, base, tz):
    from src.infrastructure.scheduler.job_scheduler import parse_schedule_expression
    return parse_schedule_expression(expr, base_dt=base, tz=tz)
