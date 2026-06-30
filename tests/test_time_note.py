from datetime import datetime, timezone, timedelta

from aurora.surfaces.telegram import _time_note


def test_time_note_includes_date_and_time():
    now = datetime(2026, 6, 30, 14, 5, tzinfo=timezone(timedelta(hours=7)))
    note = _time_note(now)
    assert "CURRENT DATE & TIME" in note
    assert "Tuesday" in note          # 2026-06-30 is a Tuesday
    assert "30 June 2026" in note     # non-padded day, portable on Windows + Linux
    assert "14:05" in note


def test_time_note_unpadded_single_digit_day():
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone(timedelta(hours=7)))
    note = _time_note(now)
    assert "5 June 2026" in note      # not "05"
