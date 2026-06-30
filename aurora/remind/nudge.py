"""Proactive reminders + progress check-ins off the commitments ledger.

The daily brief gives a once-a-morning roundup; this adds *targeted* nudges:

* **Dated items** get deadline reminders — overdue, due today, due tomorrow. These
  repeat each day until the item is done (that's the point of a reminder).
* **Undated items** get **check-ins** once they go stale (no update for
  ``stale_days``): "still waiting to hear back?" for things owed by someone else,
  "how's this going?" for the user's own open loops. Check-ins are rate-limited per
  item (via :class:`~aurora.remind.state.RemindState`) so Aurora asks, then gives it
  room — she nudges, she doesn't nag.

``plan_nudges`` is the pure, testable core (explicit data in, list of nudges out).
``run_reminders`` is the live gatherer the scheduler calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

logger = logging.getLogger("aurora.remind")

# Most nudges to send in one pass before collapsing the rest into a summary line
# (mirrors the notifier's flood cap).
_NUDGE_CAP = 6

# Send order when capping: deadlines first, check-ins last.
_PRIORITY = {"overdue": 0, "due_today": 1, "due_tomorrow": 2, "waiting": 3, "progress": 4}


@dataclass(frozen=True)
class Nudge:
    """One thing to ping the user about."""

    commitment_id: str
    text: str
    kind: str          # overdue | due_today | due_tomorrow | waiting | progress
    is_checkin: bool   # check-ins are rate-limited by stale_days; reminders repeat daily


def _age_days(today: date, iso: str) -> int | None:
    try:
        return (today - date.fromisoformat(iso)).days
    except ValueError:
        return None


def plan_nudges(commitments, today_iso: str, *, stale_days: int = 3, last_checkin=None) -> list[Nudge]:
    """Decide which open commitments deserve a nudge today (pure; no I/O).

    ``last_checkin`` maps commitment id → ISO date it was last checked in on, so a
    stale-item check-in isn't repeated until another ``stale_days`` have passed.
    """
    last_checkin = last_checkin or {}
    today = date.fromisoformat(today_iso)
    tomorrow_iso = (today + timedelta(days=1)).isoformat()
    out: list[Nudge] = []

    for c in commitments:
        if c.is_done:
            continue

        # Dated items → deadline reminders (repeat daily until done).
        if c.due:
            if c.due < today_iso:
                out.append(Nudge(c.id, f"⚠️ Overdue: {c.text} (was due {c.due})", "overdue", False))
            elif c.due == today_iso:
                out.append(Nudge(c.id, f"⏰ Due today: {c.text}", "due_today", False))
            elif c.due == tomorrow_iso:
                out.append(Nudge(c.id, f"📅 Due tomorrow: {c.text}", "due_tomorrow", False))
            # Further out → leave it to the daily brief's horizon.
            continue

        # Undated items → a check-in once they've gone stale.
        ref = c.updated or c.created
        if not ref:
            continue  # hand-added with no date: can't tell if it's stale
        age = _age_days(today, ref)
        if age is None or age < stale_days:
            continue
        last = last_checkin.get(c.id, "")
        if last:
            since = _age_days(today, last)
            if since is not None and since < stale_days:
                continue  # already checked in recently; give it room
        if c.owner == "other":
            out.append(Nudge(c.id, f"🔄 Still waiting to hear back on: {c.text}? (open since {ref})", "waiting", True))
        else:
            out.append(Nudge(c.id, f"👀 How's this going: {c.text}? (no update since {ref})", "progress", True))

    return out


def run_reminders(application, *, cap: int = _NUDGE_CAP) -> tuple[list[Nudge], int]:
    """Live gatherer the scheduler calls: read the ledger, plan nudges, record
    check-ins. Returns ``(nudges_to_send, overflow_count)``.

    Runs in a worker thread (the scheduler hands it to ``asyncio.to_thread``), so the
    state write here doesn't block the event loop.
    """
    from aurora.remind.state import RemindState

    config = application.bot_data["config"]
    ledger = application.bot_data["ledger"]
    tz = application.bot_data["tz"]
    today_iso = datetime.now(tz).date().isoformat()

    state = RemindState(config.data_dir)
    open_items = ledger.open_items()
    state.prune({c.id for c in open_items})  # forget check-ins for resolved items

    nudges = plan_nudges(
        open_items, today_iso, stale_days=config.reminder_stale_days, last_checkin=state.as_dict()
    )
    nudges.sort(key=lambda n: _PRIORITY.get(n.kind, 9))
    capped = nudges[:cap]
    overflow = len(nudges) - len(capped)

    # Only record check-ins we actually send (capped ones), so a check-in dropped to
    # the overflow line isn't suppressed next time.
    for n in capped:
        if n.is_checkin:
            state.mark_checkin(n.commitment_id, today_iso)

    return capped, overflow
