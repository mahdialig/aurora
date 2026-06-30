"""Compose the daily brief / weekly review from the commitments ledger + activity.

Follows the executive-assistant brief structure: a fixed section order so the user
absorbs it in seconds, the top items only, and the word "critical" rationed. One
``llm.complete`` call turns the structured ledger data into a warm, scannable brief.
A quiet day (nothing open, nothing handled) skips the LLM entirely.

``compose_brief`` is the testable core (explicit data in, text out). ``build_brief``
gathers the live state off the PTB ``Application`` for the scheduler.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from aurora.llm.client import Message

logger = logging.getLogger("aurora.brief")

_DAILY_SYSTEM = (
    "You are Aurora, a calm, sharp personal assistant writing the user's morning brief. "
    "Write it so they grasp the day in seconds. Use EXACTLY these sections, in this order, "
    "and OMIT any section that would be empty:\n"
    "1. Questions for you — decisions/answers you need from them, most important first.\n"
    "2. Your focus today — the few things that genuinely need them today (overdue and due-soon "
    "items they own). Top 3 max.\n"
    "3. Handled — what you already took care of (builds trust). Brief.\n"
    "4. Updates — things you're chasing or waiting on from others, and what's coming up.\n"
    "5. FYIs — anything minor worth a glance.\n"
    "Rules: ration the word 'critical' (if everything is critical, nothing is). Be concise and "
    "warm, a few words per item. Don't invent anything not in the data. Open with one short, "
    "human line (e.g. a greeting + the day's shape), then the sections as compact bullets."
)

_WEEKLY_SYSTEM = (
    "You are Aurora writing the user's weekly review. Look across the next two weeks. Use these "
    "sections, in order, omitting empty ones:\n"
    "1. Questions for you — decisions you need to make to set the week up.\n"
    "2. This week's focus — the few priorities that deserve the most attention. Top 3-5.\n"
    "3. Wins — what got done recently (builds momentum).\n"
    "4. Coming up & waiting on — deadlines in the next two weeks and what you're awaiting from "
    "others (chase candidates).\n"
    "5. Loose ends — anything undated or stalled worth deciding on.\n"
    "Be concise and warm. Don't invent anything not in the data. Open with one short framing line."
)


def _due_window(commitments, today_iso: str, days: int):
    """Split owned/open commitments into (overdue, due_soon, your_open_undated)."""
    horizon = (date.fromisoformat(today_iso) + timedelta(days=days)).isoformat()
    overdue, due_soon, undated = [], [], []
    for c in commitments:
        if c.is_done:
            continue
        # Compare on the date portion: a due may carry a time (2026-07-03T17:00).
        due_date = c.due[:10] if c.due else ""
        if due_date and due_date < today_iso:
            overdue.append(c)
        elif due_date and due_date <= horizon:
            due_soon.append(c)
        elif not c.due and c.owner == "me":
            undated.append(c)
    return overdue, due_soon, undated


def _fmt(c) -> str:
    due = f" (due {c.due})" if c.due else ""
    prog = ""
    progress = getattr(c, "progress", None)
    if progress is not None:
        done_n, total = progress
        prog = f" [{done_n}/{total} done]"
    return f"{c.text} [{c.kind}]{due}{prog}"


def build_brief_prompt(commitments, handled, *, today_iso, name, weekly, horizon_days) -> list[Message]:
    """Assemble the (system, user) messages for the brief."""
    overdue, due_soon, undated = _due_window(commitments, today_iso, horizon_days)
    waiting_on = [c for c in commitments if not c.is_done and c.owner == "other"]
    blocked = [c for c in commitments if not c.is_done and c.status == "blocked"]

    def block(title, items):
        if not items:
            return ""
        return f"\n{title}:\n" + "\n".join(f"- {_fmt(c)}" for c in items)

    who = name or "the user"
    data = [f"Today is {today_iso}. The user is {who}."]
    data.append(block("OVERDUE (they own, past due)", overdue))
    data.append(block("DUE SOON (they own)", due_soon))
    data.append(block("OPEN TASKS (they own, no date)", undated))
    data.append(block("WAITING ON OTHERS (chase candidates)", waiting_on))
    data.append(block("BLOCKED", blocked))
    if handled:
        data.append("\nHANDLED recently (by you, Aurora):\n" + "\n".join(f"- {h}" for h in handled))
    system = _WEEKLY_SYSTEM if weekly else _DAILY_SYSTEM
    return [Message("system", system), Message("user", "".join(data))]


def compose_brief(llm, commitments, handled, *, today_iso, name="", weekly=False, horizon_days=7) -> str:
    """Produce the brief text. Returns '' only on a quiet day with nothing to say."""
    open_items = [c for c in commitments if not c.is_done]
    if not open_items and not handled:
        if weekly:
            return "Weekly review: clean slate — nothing open or pending. A good week to get ahead. 🌱"
        return ""  # quiet day: the scheduler simply sends nothing
    try:
        return llm.complete(
            build_brief_prompt(
                commitments, handled,
                today_iso=today_iso, name=name, weekly=weekly, horizon_days=horizon_days,
            ),
            temperature=0.4,
        ).strip()
    except Exception:  # noqa: BLE001 - never let a brief failure crash the scheduler
        logger.exception("Brief composition failed.")
        # Fall back to a plain, un-prettified list so the user still gets something.
        lines = [f"Brief for {today_iso}:"]
        for c in open_items[:8]:
            lines.append(f"• {_fmt(c)}")
        return "\n".join(lines)


def build_brief(application, *, weekly: bool) -> str:
    """Gather live state off the Application and compose the brief (for the scheduler)."""
    config = application.bot_data["config"]
    llm = application.bot_data["llm"]
    ledger = application.bot_data["ledger"]
    activity = application.bot_data.get("activity")
    memory = application.bot_data["memory"]

    tz_today = date.today().isoformat()
    horizon = config.weekly_horizon_days if weekly else config.brief_horizon_days
    handled = activity.since(tz_today) if (activity and not weekly) else (
        activity.since((date.fromisoformat(tz_today) - timedelta(days=7)).isoformat()) if activity else []
    )
    return compose_brief(
        llm,
        ledger.entries(),
        handled,
        today_iso=tz_today,
        name=memory.display_name() or "",
        weekly=weekly,
        horizon_days=horizon,
    )
