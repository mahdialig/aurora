"""A bounded, restart-safe log of actions Aurora took on the user's behalf.

Feeds the daily brief's "what I already handled" section (visibility = trust). A
tiny JSON ring buffer (``data/activity.json``) of ``{on, text}`` entries, bounded
so it can't grow without limit.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger("aurora.activity")

_MAX = 200


class ActivityLog:
    """Recent actions Aurora performed, each stamped with the local date."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "activity.json"
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            logger.warning("Could not read %s; starting fresh.", self.path)
            return []
        return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []

    def record(self, text: str, *, on: str | None = None) -> None:
        text = text.strip()
        if not text:
            return
        self._items.append({"on": on or date.today().isoformat(), "text": text})
        if len(self._items) > _MAX:
            self._items = self._items[-_MAX:]
        self._save()

    def since(self, day: str) -> list[str]:
        """Texts of actions recorded on or after ``day`` (ISO date)."""
        return [x["text"] for x in self._items if x.get("on", "") >= day]

    def on_day(self, day: str) -> list[str]:
        """Texts of actions recorded exactly on ``day``."""
        return [x["text"] for x in self._items if x.get("on", "") == day]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._items), encoding="utf-8")
