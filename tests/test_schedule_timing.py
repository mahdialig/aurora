from datetime import datetime

import pytest

from aurora.schedule.runner import DAILY_JOB, WEEKLY_JOB, pending_jobs
from aurora.schedule.state import ScheduleState
from aurora.schedule.timing import daily_due, parse_hhmm, weekly_due


def test_parse_hhmm():
    assert parse_hhmm("07:30").hour == 7
    assert parse_hhmm("07:30").minute == 30
    with pytest.raises(ValueError):
        parse_hhmm("25:00")


def test_daily_due_after_fire_time():
    now = datetime(2026, 6, 30, 8, 0)  # 08:00, fire at 07:00
    assert daily_due(now, "07:00", last_fired="") is True


def test_daily_not_due_before_fire_time():
    now = datetime(2026, 6, 30, 6, 0)  # before 07:00
    assert daily_due(now, "07:00", last_fired="") is False


def test_daily_not_due_if_already_fired_today():
    now = datetime(2026, 6, 30, 9, 0)
    assert daily_due(now, "07:00", last_fired="2026-06-30") is False


def test_daily_offline_catch_up():
    # Bot was off at 07:00, starts at 11:00 same day, never fired today -> still due.
    now = datetime(2026, 6, 30, 11, 0)
    assert daily_due(now, "07:00", last_fired="2026-06-29") is True


def test_daily_due_across_day_boundary():
    # Fired yesterday; new day, after fire time -> due again.
    now = datetime(2026, 7, 1, 7, 30)
    assert daily_due(now, "07:00", last_fired="2026-06-30") is True


def test_weekly_due_only_on_weekday():
    # 2026-06-29 is a Monday (weekday 0).
    monday = datetime(2026, 6, 29, 8, 0)
    tuesday = datetime(2026, 6, 30, 8, 0)
    assert weekly_due(monday, weekday=0, fire_time="07:00", last_fired="") is True
    assert weekly_due(tuesday, weekday=0, fire_time="07:00", last_fired="") is False


def test_pending_jobs_combines(tmp_path):
    state = ScheduleState(tmp_path)
    monday_8am = datetime(2026, 6, 29, 8, 0)
    due = pending_jobs(
        monday_8am, state,
        brief_enabled=True, brief_time="07:00",
        weekly_enabled=True, weekly_day=0, weekly_time="07:30",
    )
    assert due == [DAILY_JOB, WEEKLY_JOB]


def test_pending_jobs_respects_disabled(tmp_path):
    state = ScheduleState(tmp_path)
    now = datetime(2026, 6, 30, 8, 0)
    due = pending_jobs(
        now, state,
        brief_enabled=False, brief_time="07:00",
        weekly_enabled=False, weekly_day=0, weekly_time="07:30",
    )
    assert due == []


def test_schedule_state_round_trip(tmp_path):
    st = ScheduleState(tmp_path)
    assert st.last_fired(DAILY_JOB) == ""
    st.mark_fired(DAILY_JOB, "2026-06-30")
    assert ScheduleState(tmp_path).last_fired(DAILY_JOB) == "2026-06-30"


def test_pending_jobs_not_repeated_after_fire(tmp_path):
    state = ScheduleState(tmp_path)
    now = datetime(2026, 6, 30, 8, 0)
    state.mark_fired(DAILY_JOB, "2026-06-30")
    due = pending_jobs(
        now, state,
        brief_enabled=True, brief_time="07:00",
        weekly_enabled=False, weekly_day=0, weekly_time="07:30",
    )
    assert DAILY_JOB not in due
