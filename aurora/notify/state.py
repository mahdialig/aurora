"""Restart-safe tracking of which emails Aurora has already considered.

A tiny JSON file (``data/notify_state.json``) maps each account label to the list
of message ids she's already seen, so the poller only acts on genuinely new mail
and survives restarts. Bounded per account so the file can't grow without limit.

First contact with an account (no entry yet) is special: the poller seeds all
current unread as seen WITHOUT notifying, so starting the bot doesn't dump the
whole backlog. Because state persists, mail that lands while the bot is off is
still caught on the next run (it's genuinely unseen).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("aurora.notify")

_MAX_PER_ACCOUNT = 500


class NotifyState:
    """Per-account set of already-seen message ids, persisted as JSON."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "notify_state.json"
        self._seen: dict[str, list[str]] = self._load()

    def _load(self) -> dict[str, list[str]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            logger.warning("Could not read %s; starting fresh.", self.path)
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): [str(i) for i in v] for k, v in data.items() if isinstance(v, list)}

    def is_first_contact(self, account: str) -> bool:
        """True when this account has no recorded state yet."""
        return account not in self._seen

    def unseen(self, account: str, ids: list[str]) -> list[str]:
        """Return the ids (order preserved) not previously seen for ``account``."""
        known = set(self._seen.get(account, []))
        return [i for i in ids if i not in known]

    def mark_seen(self, account: str, ids: list[str]) -> None:
        """Record ``ids`` as seen (bounded to the most recent ones), then persist."""
        current = self._seen.get(account, [])
        known = set(current)
        current = current + [i for i in ids if i not in known]
        if len(current) > _MAX_PER_ACCOUNT:
            current = current[-_MAX_PER_ACCOUNT:]
        self._seen[account] = current
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._seen), encoding="utf-8")
