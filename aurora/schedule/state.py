"""Restart-safe record of when each scheduled job last fired.

A tiny JSON file (``data/schedule_state.json``) maps a job name to the local date
(``YYYY-MM-DD``) it last ran. Combined with :mod:`aurora.schedule.timing`, this
prevents double-sending a brief within a day and survives restarts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("aurora.schedule")


class ScheduleState:
    """Per-job last-fired date, persisted as JSON."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "schedule_state.json"
        self._fired: dict[str, str] = self._load()

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

    def last_fired(self, job: str) -> str:
        """The local ISO date this job last fired, or '' if never."""
        return self._fired.get(job, "")

    def mark_fired(self, job: str, day: str) -> None:
        self._fired[job] = day
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._fired), encoding="utf-8")
