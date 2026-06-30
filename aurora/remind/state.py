"""Restart-safe record of when each commitment was last checked in on.

A tiny JSON file (``data/remind_state.json``) mapping commitment id → local ISO date
of its last progress/waiting check-in. This is what rate-limits check-ins so Aurora
asks about a stale item, then leaves it alone for ``stale_days`` rather than nagging
every pass. Deadline reminders don't use this — they repeat daily until done.

Mirrors :class:`~aurora.schedule.state.ScheduleState`: low-stakes bookkeeping, so a
plain (non-atomic) write is fine; a corrupt/missing file just starts fresh.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("aurora.remind")


class RemindState:
    """Per-commitment last-check-in date, persisted as JSON."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "remind_state.json"
        self._checkins: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            logger.warning("Could not read %s; starting fresh.", self.path)
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}

    def last_checkin(self, commitment_id: str) -> str:
        return self._checkins.get(commitment_id, "")

    def as_dict(self) -> dict[str, str]:
        return dict(self._checkins)

    def mark_checkin(self, commitment_id: str, day: str) -> None:
        self._checkins[commitment_id] = day
        self._save()

    def prune(self, valid_ids: set[str]) -> None:
        """Drop entries for commitments that no longer exist (done/removed)."""
        stale = [cid for cid in self._checkins if cid not in valid_ids]
        if stale:
            for cid in stale:
                del self._checkins[cid]
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._checkins), encoding="utf-8")
