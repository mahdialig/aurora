"""The background scheduler loop — fires the daily brief and weekly review.

A dependency-free asyncio loop with a coarse 60-second tick (the same hand-rolled
style as the notifier; PTB's JobQueue needs APScheduler, which isn't installed). On
each tick it asks :mod:`aurora.schedule.timing` which jobs are due, runs them, and
records the fire date via :class:`ScheduleState` so nothing double-sends.

``pending_jobs`` is the pure, testable core. ``start_scheduler`` wires it to a
running PTB ``Application`` (call from ``post_init``).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aurora.schedule.state import ScheduleState
from aurora.schedule.timing import daily_due, weekly_due

logger = logging.getLogger("aurora.schedule")

_TICK_SECONDS = 60

DAILY_JOB = "daily_brief"
WEEKLY_JOB = "weekly_review"
REMINDER_JOB = "reminders"


def resolve_tz(name: str):
    """A tzinfo for ``name``, falling back to fixed UTC+7 (Jakarta has no DST)."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - missing tzdata on Windows, or a bad name
        logger.warning("Timezone %r unavailable; falling back to fixed UTC+7.", name)
        return timezone(timedelta(hours=7))


def pending_jobs(
    now_local: datetime,
    state: ScheduleState,
    *,
    brief_enabled: bool,
    brief_time: str,
    weekly_enabled: bool,
    weekly_day: int,
    weekly_time: str,
    reminder_enabled: bool = False,
    reminder_time: str = "09:00",
) -> list[str]:
    """Pure: which jobs are due right now. Does not mutate state."""
    due: list[str] = []
    if brief_enabled and daily_due(now_local, brief_time, state.last_fired(DAILY_JOB)):
        due.append(DAILY_JOB)
    if weekly_enabled and weekly_due(now_local, weekly_day, weekly_time, state.last_fired(WEEKLY_JOB)):
        due.append(WEEKLY_JOB)
    if reminder_enabled and daily_due(now_local, reminder_time, state.last_fired(REMINDER_JOB)):
        due.append(REMINDER_JOB)
    return due


def start_scheduler(application) -> None:
    """Begin the background scheduler on the running Application (call from post_init)."""
    config = application.bot_data["config"]
    uid = config.allowed_user_id
    tz = resolve_tz(config.timezone)
    state = ScheduleState(config.data_dir)
    application.bot_data["schedule_state"] = state

    async def fire(job: str) -> None:
        # Imported here to avoid a heavy import at module load and to keep the
        # scheduler decoupled from how each job is composed.
        if job == REMINDER_JOB:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            from aurora.remind.nudge import run_reminders

            nudges, overflow = await asyncio.to_thread(run_reminders, application)
            for n in nudges:
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("✅ Done", callback_data=f"rdone:{n.commitment_id}")]]
                )
                await application.bot.send_message(chat_id=uid, text=n.text, reply_markup=keyboard)
            if overflow > 0:
                await application.bot.send_message(
                    chat_id=uid, text=f"…and {overflow} more open item(s) — see /agenda."
                )
            return

        from aurora.brief.compose import build_brief

        text = await asyncio.to_thread(build_brief, application, weekly=(job == WEEKLY_JOB))
        if text:
            await application.bot.send_message(chat_id=uid, text=text)

    async def loop() -> None:
        logger.info(
            "Scheduler started (tz=%s, brief=%s@%s, weekly=%s day%s@%s, reminders=%s@%s).",
            config.timezone, config.brief_enabled, config.brief_time,
            config.weekly_review_enabled, config.weekly_review_day, config.weekly_review_time,
            config.reminder_enabled, config.reminder_time,
        )
        while True:
            try:
                now_local = datetime.now(tz)
                due = pending_jobs(
                    now_local, state,
                    brief_enabled=config.brief_enabled,
                    brief_time=config.brief_time,
                    weekly_enabled=config.weekly_review_enabled,
                    weekly_day=config.weekly_review_day,
                    weekly_time=config.weekly_review_time,
                    reminder_enabled=config.reminder_enabled,
                    reminder_time=config.reminder_time,
                )
                for job in due:
                    await fire(job)
                    state.mark_fired(job, now_local.date().isoformat())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - never let a bad tick stop the loop
                logger.exception("Scheduler tick failed")
            await asyncio.sleep(_TICK_SECONDS)

    task = asyncio.create_task(loop())
    application.bot_data["schedule_task"] = task


def stop_scheduler(application) -> None:
    """Cancel the background scheduler loop (call from post_shutdown)."""
    task = application.bot_data.get("schedule_task")
    if task is not None:
        task.cancel()
