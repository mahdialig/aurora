"""File-backed memory store.

Aurora's memory is a plain markdown file the user can read and edit by hand —
``data/memory/memory.md`` — holding one entry per line with inline provenance:

    # Aurora's memory of the user

    - [2026-06-29] (you told me) I'm Mahdi — startup founder, also PM + developer.
    - [2026-06-29] (you told me) Keep replies concise.

The file is the source of truth. This module just reads, appends to, and rewrites
it. No database, no network — deliberately transparent and owned (and trivially
testable).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_HEADER = "# Aurora's memory of the user"

# Parses a markdown bullet, with optional [date] and (source) prefixes so that
# hand-edited lines like "- just some note" still load.
_ENTRY_RE = re.compile(
    r"^-\s*"
    r"(?:\[(?P<date>[^\]]*)\]\s*)?"
    r"(?:\((?P<source>[^)]*)\)\s*)?"
    r"(?P<text>.+?)\s*$"
)

# Patterns for guessing the user's name from memory, for a personal greeting.
_NAME_RE = re.compile(
    r"\b(?:i'?m|i am|my name is|name:|call me)\s+(?P<name>[A-Za-z][\w'-]*)",
    re.IGNORECASE,
)
_NAME_STOPWORDS = {
    "a", "an", "the", "not", "just", "currently", "really", "very", "now",
    "your", "his", "her", "their", "working", "trying", "going",
}


@dataclass(frozen=True)
class MemoryEntry:
    """One thing Aurora knows."""

    text: str
    on: str = ""  # ISO date the entry was added (free-form; may be empty if hand-edited)
    source: str = ""  # provenance, e.g. "you told me"

    def to_line(self) -> str:
        parts = ["-"]
        if self.on:
            parts.append(f"[{self.on}]")
        if self.source:
            parts.append(f"({self.source})")
        parts.append(self.text)
        return " ".join(parts)


class MemoryStore:
    """Reads/writes Aurora's memory markdown file under ``<data_dir>/memory``."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "memory" / "memory.md"

    # --- reading -----------------------------------------------------------

    def entries(self) -> list[MemoryEntry]:
        if not self.path.exists():
            return []
        out: list[MemoryEntry] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line.startswith("- "):
                continue
            m = _ENTRY_RE.match(line)
            if not m:
                continue
            text = (m.group("text") or "").strip()
            if not text:
                continue
            out.append(
                MemoryEntry(
                    text=text,
                    on=(m.group("date") or "").strip(),
                    source=(m.group("source") or "").strip(),
                )
            )
        return out

    def is_empty(self) -> bool:
        return not self.entries()

    def display_name(self) -> str | None:
        """Best-effort guess of the user's name, for greetings. None if unknown."""
        for entry in self.entries():
            m = _NAME_RE.search(entry.text)
            if not m:
                continue
            name = m.group("name").strip()
            if name.lower() in _NAME_STOPWORDS:
                continue
            return name
        return None

    # --- writing -----------------------------------------------------------

    def add(self, text: str, source: str = "you told me") -> MemoryEntry:
        """Append a new memory with today's date. Returns the stored entry."""
        text = text.strip()
        if not text:
            raise ValueError("Cannot remember an empty note.")
        entry = MemoryEntry(text=text, on=date.today().isoformat(), source=source)
        self._write(self.entries() + [entry])
        return entry

    def forget(self, query: str | int) -> MemoryEntry | None:
        """Remove an entry by 1-based index or first case-insensitive substring match.

        Returns the removed entry, or None if nothing matched.
        """
        items = self.entries()
        idx: int | None = None

        if isinstance(query, int) or (isinstance(query, str) and query.strip().isdigit()):
            n = int(query)
            if 1 <= n <= len(items):
                idx = n - 1
        else:
            needle = str(query).strip().lower()
            for i, entry in enumerate(items):
                if needle and needle in entry.text.lower():
                    idx = i
                    break

        if idx is None:
            return None
        removed = items.pop(idx)
        self._write(items)
        return removed

    def _write(self, items: list[MemoryEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [_HEADER, ""]
        lines.extend(entry.to_line() for entry in items)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- prompting ---------------------------------------------------------

    def render_for_prompt(self) -> str:
        """A compact block describing what Aurora knows, for the system prompt."""
        items = self.entries()
        if not items:
            return (
                "\n\nMEMORY: You don't know anything about this user yet. "
                "If they share a durable fact or preference about themselves, offer to remember it."
            )
        lines = "\n".join(f"- {entry.text}" for entry in items)
        return (
            "\n\nMEMORY — what you currently know about the user "
            "(treat as true; rely on it):\n" + lines
        )
