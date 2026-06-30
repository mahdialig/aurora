"""Pure due-time logic for recurring jobs — no asyncio, no clock, fully testable.

A job fires at most once per local day. The "due" check compares the current
*local* time against a configured fire time, plus the last date the job fired:

* **Daily** (the morning brief): due when today's fire time has passed and the job
  hasn't already fired today. This gives free offline catch-up — if the bot was
  down at the fire time and starts later the same day, it still fires once.
* **Weekly** (the review): same, but only on the configured weekday. A review
  missed because the bot was off all day is skipped rather than fired on the wrong
  day (firing late on the right weekday is fine; firing on the wrong one isn't).

Times are ``"HH:MM"`` 24-hour strings; weekday is 0=Monday..6=Sunday (``date.weekday()``).
"""

from __future__ import annotations

from datetime import datetime, time


def parse_hhmm(value: str) -> time:
    """Parse ``"HH:MM"`` into a ``time``. Raises ValueError on bad input."""
    hh, _, mm = value.strip().partition(":")
    hour, minute = int(hh), int(mm)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"Invalid time {value!r}")
    return time(hour, minute)


def daily_due(now_local: datetime, fire_time: str, last_fired: str) -> bool:
    """True if the daily job should run now (fire time passed, not yet fired today)."""
    today = now_local.date().isoformat()
    if last_fired == today:
        return False
    return now_local.timetz().replace(tzinfo=None) >= parse_hhmm(fire_time)


def weekly_due(now_local: datetime, weekday: int, fire_time: str, last_fired: str) -> bool:
    """True if the weekly job should run now (right weekday, fire time passed, not fired today)."""
    if now_local.weekday() != weekday:
        return False
    return daily_due(now_local, fire_time, last_fired)
