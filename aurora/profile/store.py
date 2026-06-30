"""File-backed preference profile — the seed of Aurora's "semantic" memory.

A small, structured companion to :class:`~aurora.memory.store.MemoryStore`. Where
memory is a free-form list of facts, the profile is a set of **keyed** standing
preferences (how to address the user, their working rhythm, email voice, what to
escalate, who always gets through, the notification threshold) — the things a good
EA learns about their principal in week one. It is a plain markdown file the user
can read and edit by hand (``data/profile/profile.md``), one field per line:

    # Aurora's profile of the user

    - preferred_name: Aji · on:2026-06-30 src:onboarding
    - work_hours: 9am–6pm WIB, heads-down mornings · on:2026-06-30 src:onboarding

The ``<key>: <value>`` before ``·`` is the human-readable preference; the trailing
``key:val`` block is provenance (``on`` = ISO date set, ``src`` = where it came
from). Lines without a ``·`` (hand-added) still load with empty provenance.

Like the ledger (and unlike memory), writes are **keyed**: ``set`` upserts by key,
so re-onboarding or a later correction updates the right field instead of
duplicating, and a forgotten field truly disappears (D8). Writes are atomic
(tmp + ``os.replace``) and lock-guarded so a crash never corrupts the file.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_HEADER = "# Aurora's profile of the user"

# Splits a line into "<key: value> · <key:val key:val ...>". The metadata block is
# optional so a hand-written "- reply_tone: warm" still loads.
_SEP = " · "
# One key:val provenance token. Values run to the next space (dates/sources never
# contain spaces).
_KV_RE = re.compile(r"(?P<key>[a-z_]+):(?P<val>\S+)")


@dataclass(frozen=True)
class ProfileField:
    """One standing preference Aurora keeps about the user."""

    key: str                # stable slug, e.g. "reply_tone"
    value: str              # the preference, free text
    on: str = ""            # ISO date set
    source: str = ""        # provenance: onboarding | correction | you told me

    def to_line(self) -> str:
        line = f"- {self.key}: {self.value}"
        meta = []
        if self.on:
            meta.append(f"on:{self.on}")
        if self.source:
            meta.append(f"src:{self.source}")
        if meta:
            line += _SEP + " ".join(meta)
        return line


class ProfileStore:
    """Reads/writes the profile markdown file under ``<data_dir>/profile``."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "profile" / "profile.md"
        self._lock = threading.Lock()

    # --- reading -----------------------------------------------------------

    def fields(self) -> list[ProfileField]:
        if not self.path.exists():
            return []
        out: list[ProfileField] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line.startswith("- "):
                continue
            body = line[2:].strip()
            if not body:
                continue
            left, sep, meta = body.partition(_SEP)
            key, ksep, value = left.partition(":")
            key = key.strip()
            value = value.strip()
            if not key or not ksep or not value:
                continue
            prov = {m.group("key"): m.group("val") for m in _KV_RE.finditer(meta)} if sep else {}
            out.append(
                ProfileField(
                    key=key,
                    value=value,
                    on=prov.get("on", ""),
                    source=prov.get("src", ""),
                )
            )
        return out

    def get(self, key: str) -> ProfileField | None:
        key = key.strip()
        for f in self.fields():
            if f.key == key:
                return f
        return None

    def is_empty(self) -> bool:
        return not self.fields()

    # --- writing -----------------------------------------------------------

    def set(self, key: str, value: str, *, source: str = "onboarding") -> ProfileField:
        """Upsert a preference by key — replaces an existing field with the same key
        (so corrections update in place, no duplicates), else appends."""
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError("A profile field needs a key.")
        if not value:
            raise ValueError("A profile field needs a value.")
        new = ProfileField(key=key, value=value, on=date.today().isoformat(), source=source.strip())
        with self._lock:
            items = self.fields()
            replaced = False
            out: list[ProfileField] = []
            for f in items:
                if f.key == key:
                    out.append(new)
                    replaced = True
                else:
                    out.append(f)
            if not replaced:
                out.append(new)
            self._write(out)
        return new

    def remove(self, key: str) -> ProfileField | None:
        """Drop a field by key. Forgetting truly reverts behavior (D8)."""
        key = key.strip()
        with self._lock:
            items = self.fields()
            for i, f in enumerate(items):
                if f.key == key:
                    removed = items.pop(i)
                    self._write(items)
                    return removed
        return None

    def _write(self, items: list[ProfileField]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [_HEADER, ""]
        lines.extend(f.to_line() for f in items)
        data = "\n".join(lines) + "\n"
        # Atomic: write to a temp file in the same dir, then replace. A crash leaves
        # either the old file or the new one — never a half-written profile.
        tmp = self.path.with_suffix(".md.tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, self.path)

    # --- prompting ---------------------------------------------------------

    def render_for_prompt(self) -> str:
        """The standing-preferences block for the system prompt."""
        items = self.fields()
        if not items:
            return (
                "\n\nPROFILE: You don't yet know the user's working preferences (tone, "
                "rhythm, what to escalate, who matters). If it would help you serve them "
                "better, suggest they run /onboard so you can tailor how you work."
            )
        lines = "\n".join(f"- {f.key.replace('_', ' ')}: {f.value}" for f in items)
        return (
            "\n\nPROFILE — the user's standing preferences (treat as standing instructions; "
            "follow them unless they say otherwise this turn):\n" + lines
        )
