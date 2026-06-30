"""File-backed commitments ledger.

Aurora's "don't-miss-a-thing" substrate: a single source of truth for open loops —
things the user owes someone, replies awaited from others, deadlines, and meeting
prep. Like memory, it's a plain markdown file the user can read and edit by hand
(``data/ledger/commitments.md``), one commitment per line:

    # Aurora's commitments ledger

    - Reply to Sara about the proposal · kind:reply owner:me status:open due:2026-07-03 id:c1 src:email:personal:abc created:2026-06-30 updated:2026-06-30
    - Quarterly report deadline · kind:deadline owner:me status:open due:2026-07-10 id:c2 created:2026-06-30 updated:2026-06-30

The text before ``·`` is the human-readable part; the trailing ``key:val`` block is
machine state. Lines without a ``·`` (hand-added notes) still load as open tasks.

Unlike :class:`~aurora.memory.store.MemoryStore`, this file is the source of truth
for what must not slip, so writes are atomic (tmp + ``os.replace``) and guarded by a
lock — a crash mid-write must never corrupt it. Done items are kept in the file
(so the weekly review can reflect on them) until ``prune_done`` trims them.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

_HEADER = "# Aurora's commitments ledger"

KINDS = ("task", "reply", "deadline", "meeting-prep")
STATUSES = ("open", "waiting", "blocked", "done")
OWNERS = ("me", "other")

# Splits a line into "<text> · <key:val key:val ...>". The metadata block is
# optional so a hand-written "- call the dentist" still loads.
_SEP = " · "
# One key:val token in the metadata block. Values run to the next space (ids,
# dates, and source keys never contain spaces).
_KV_RE = re.compile(r"(?P<key>[a-z_]+):(?P<val>\S+)")
# A GitHub-style task-list child line: "  - [ ] step" / "  - [x] step". Matched
# against the *stripped* line, so a parent line ("- text · meta") never matches
# (its char after "- " is text, not "["). Steps belong to the most recent parent.
_STEP_RE = re.compile(r"-\s*\[(?P<mark>[ xX])\]\s+(?P<text>.+)")


def _coerce(value: str, allowed: tuple[str, ...], default: str) -> str:
    value = value.strip().lower()
    return value if value in allowed else default


def _due_date(due: str) -> str:
    """The date portion of a ``due`` that may carry a time (``2026-07-03T17:00``).

    Equality and ``due_on_or_before`` comparisons must run on the date, not the
    raw string — otherwise a timed due never equals a bare date and sorts after
    one for the same day. Plain ``<`` ordering already works (fixed-width ISO)."""
    return due[:10]


@dataclass(frozen=True)
class Step:
    """One definition-of-done item under a commitment's checklist."""

    text: str
    done: bool = False


def _as_steps(steps: list[str] | list[Step] | None) -> tuple[Step, ...]:
    """Coerce a list of step texts (or ``Step``s) into a steps tuple, dropping blanks.

    A checklist needs at least two distinct items to be meaningful — a single step
    just restates the parent — so 0 or 1 step collapses to a flat task (``()``)."""
    if not steps:
        return ()
    out: list[Step] = []
    for s in steps:
        if isinstance(s, Step):
            if s.text.strip():
                out.append(s)
        elif str(s).strip():
            out.append(Step(text=str(s).strip()))
    return tuple(out) if len(out) >= 2 else ()


@dataclass(frozen=True)
class Commitment:
    """One open loop Aurora is tracking for the user.

    A commitment may own a *checklist* (``steps``): each step is one
    definition-of-done item. Zero steps = a flat task = today's exact behavior."""

    id: str
    text: str
    kind: str = "task"          # task | reply | deadline | meeting-prep
    owner: str = "me"           # me | other
    status: str = "open"        # open | waiting | blocked | done
    due: str = ""               # ISO date or date+time (2026-07-03T17:00), or "" if none
    source: str = ""            # provenance, e.g. "email:personal:<id>" or "chat"
    created: str = ""           # ISO date added
    updated: str = ""           # ISO date last changed
    remind: bool = True         # per-task proactive-reminder opt-in (default on)
    steps: tuple[Step, ...] = ()  # checklist; empty = flat task

    @property
    def is_done(self) -> bool:
        if self.steps:
            return all(s.done for s in self.steps)
        return self.status == "done"

    @property
    def progress(self) -> tuple[int, int] | None:
        """(done, total) for a checklist, or None when flat."""
        if not self.steps:
            return None
        return (sum(1 for s in self.steps if s.done), len(self.steps))

    def open_step_texts(self) -> list[str]:
        return [s.text for s in self.steps if not s.done]

    def to_line(self) -> str:
        meta = [f"kind:{self.kind}", f"owner:{self.owner}", f"status:{self.status}"]
        if not self.remind:
            meta.append("remind:off")
        if self.due:
            meta.append(f"due:{self.due}")
        meta.append(f"id:{self.id}")
        if self.source:
            meta.append(f"src:{self.source}")
        if self.created:
            meta.append(f"created:{self.created}")
        if self.updated:
            meta.append(f"updated:{self.updated}")
        return f"- {self.text}{_SEP}{' '.join(meta)}"

    def step_lines(self) -> list[str]:
        """GitHub-style task-list child lines (empty for a flat task)."""
        return [f"  - [{'x' if s.done else ' '}] {s.text}" for s in self.steps]


class LedgerStore:
    """Reads/writes the commitments markdown file under ``<data_dir>/ledger``."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "ledger" / "commitments.md"
        self._lock = threading.Lock()

    # --- reading -----------------------------------------------------------

    def entries(self) -> list[Commitment]:
        if not self.path.exists():
            return []
        out: list[Commitment] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            # A checklist child line attaches to the most recent parent. Checked
            # before the parent path because a stripped step also starts with "- ".
            step_m = _STEP_RE.fullmatch(line)
            if step_m and out:
                step = Step(text=step_m.group("text").strip(), done=step_m.group("mark") in "xX")
                out[-1] = replace(out[-1], steps=out[-1].steps + (step,))
                continue
            if not line.startswith("- "):
                continue
            body = line[2:].strip()
            if not body:
                continue
            text, sep, meta = body.partition(_SEP)
            text = text.strip()
            fields = {m.group("key"): m.group("val") for m in _KV_RE.finditer(meta)} if sep else {}
            if not text:
                continue
            out.append(
                Commitment(
                    id=fields.get("id", ""),
                    text=text,
                    kind=_coerce(fields.get("kind", ""), KINDS, "task"),
                    owner=_coerce(fields.get("owner", ""), OWNERS, "me"),
                    status=_coerce(fields.get("status", ""), STATUSES, "open"),
                    due=fields.get("due", ""),
                    source=fields.get("src", ""),
                    created=fields.get("created", ""),
                    updated=fields.get("updated", ""),
                    remind=fields.get("remind", "on").lower() != "off",
                )
            )
        # Backfill ids for hand-added lines so update/done can target them.
        return self._with_ids(out)

    def _with_ids(self, items: list[Commitment]) -> list[Commitment]:
        if all(c.id for c in items):
            return items
        next_n = self._max_id(items) + 1
        fixed: list[Commitment] = []
        for c in items:
            if c.id:
                fixed.append(c)
            else:
                fixed.append(replace(c, id=f"c{next_n}"))
                next_n += 1
        return fixed

    @staticmethod
    def _max_id(items: list[Commitment]) -> int:
        biggest = 0
        for c in items:
            m = re.fullmatch(r"c(\d+)", c.id or "")
            if m:
                biggest = max(biggest, int(m.group(1)))
        return biggest

    def get(self, commitment_id: str) -> Commitment | None:
        for c in self.entries():
            if c.id == commitment_id:
                return c
        return None

    def query(
        self,
        *,
        status: str | None = None,
        owner: str | None = None,
        kind: str | None = None,
        include_done: bool = False,
        due_on_or_before: str | None = None,
    ) -> list[Commitment]:
        """Filter commitments. By default excludes done items."""
        out = []
        for c in self.entries():
            if not include_done and c.is_done:
                continue
            if status is not None and c.status != status:
                continue
            if owner is not None and c.owner != owner:
                continue
            if kind is not None and c.kind != kind:
                continue
            if due_on_or_before is not None and (not c.due or _due_date(c.due) > due_on_or_before):
                continue
            out.append(c)
        return out

    def open_items(self) -> list[Commitment]:
        """All not-done commitments, soonest due first (undated last)."""
        items = self.query()
        return sorted(items, key=lambda c: (c.due == "", c.due))

    # --- writing -----------------------------------------------------------

    def add(
        self,
        text: str,
        *,
        kind: str = "task",
        owner: str = "me",
        due: str = "",
        source: str = "",
        status: str = "open",
        steps: list[str] | list[Step] | None = None,
        remind: bool = True,
    ) -> Commitment:
        """Add a commitment. If ``source`` is a *specific provenance key* matching an
        existing one, returns that (no duplicate) — so the chat and email-auto-capture
        paths can't double-store the same email. ``steps`` may be step texts or ``Step``s.

        Dedup applies ONLY to structured provenance keys (those containing ``:``, e.g.
        ``email:work:ab12``), never to a generic source like ``chat`` — otherwise every
        chat-tracked item would collapse onto the first one and ``add`` would return an
        unrelated old task."""
        text = text.strip()
        if not text:
            raise ValueError("Cannot track an empty commitment.")
        with self._lock:
            items = self.entries()
            if source and ":" in source:
                for c in items:
                    if c.source == source:
                        return c
            today = date.today().isoformat()
            new = Commitment(
                id=f"c{self._max_id(items) + 1}",
                text=text,
                kind=_coerce(kind, KINDS, "task"),
                owner=_coerce(owner, OWNERS, "me"),
                status=_coerce(status, STATUSES, "open"),
                due=due.strip(),
                source=source.strip(),
                created=today,
                updated=today,
                remind=bool(remind),
                steps=_as_steps(steps),
            )
            self._write(items + [new])
            return new

    def update(self, commitment_id: str, **changes) -> Commitment | None:
        """Update fields of a commitment by id. Returns the new value, or None."""
        allowed = {"text", "kind", "owner", "status", "due", "remind"}
        clean = {k: v for k, v in changes.items() if k in allowed and v is not None}
        with self._lock:
            items = self.entries()
            for i, c in enumerate(items):
                if c.id != commitment_id:
                    continue
                if "kind" in clean:
                    clean["kind"] = _coerce(clean["kind"], KINDS, c.kind)
                if "owner" in clean:
                    clean["owner"] = _coerce(clean["owner"], OWNERS, c.owner)
                if "status" in clean:
                    clean["status"] = _coerce(clean["status"], STATUSES, c.status)
                updated = replace(c, **clean, updated=date.today().isoformat())
                items[i] = updated
                self._write(items)
                return updated
        return None

    def mark_done(self, commitment_id: str) -> Commitment | None:
        """Mark a commitment done (kept in-file for the weekly review). Also ticks
        every step so the file reflects completion. The *guard* (confirm when steps
        are still open) lives at the call sites — they check ``open_steps`` first."""
        with self._lock:
            items = self.entries()
            for i, c in enumerate(items):
                if c.id != commitment_id:
                    continue
                done_steps = tuple(replace(s, done=True) for s in c.steps)
                items[i] = replace(c, status="done", steps=done_steps,
                                   updated=date.today().isoformat())
                self._write(items)
                return items[i]
        return None

    def open_steps(self, commitment_id: str) -> list[Step]:
        """Not-done steps of a commitment (empty for a flat or fully-done item)."""
        c = self.get(commitment_id)
        return [s for s in c.steps if not s.done] if c else []

    def set_step(
        self,
        commitment_id: str,
        *,
        index: int | None = None,
        text: str | None = None,
        done: bool = True,
    ) -> Commitment | None:
        """Tick (or untick) one step, addressed by index or by matching text.

        When this leaves every step done, the parent auto-completes (status=done)."""
        with self._lock:
            items = self.entries()
            for i, c in enumerate(items):
                if c.id != commitment_id or not c.steps:
                    continue
                target = self._step_index(c, index, text)
                if target is None:
                    return None
                steps = list(c.steps)
                steps[target] = replace(steps[target], done=done)
                steps_t = tuple(steps)
                status = "done" if all(s.done for s in steps_t) else (
                    "open" if c.status == "done" else c.status
                )
                items[i] = replace(c, steps=steps_t, status=status,
                                   updated=date.today().isoformat())
                self._write(items)
                return items[i]
        return None

    @staticmethod
    def _step_index(c: Commitment, index: int | None, text: str | None) -> int | None:
        if index is not None and 0 <= index < len(c.steps):
            return index
        if text:
            want = text.strip().lower()
            # Exact match first, then a forgiving substring match.
            for i, s in enumerate(c.steps):
                if s.text.strip().lower() == want:
                    return i
            for i, s in enumerate(c.steps):
                if want in s.text.strip().lower():
                    return i
        return None

    def remove(self, commitment_id: str) -> Commitment | None:
        with self._lock:
            items = self.entries()
            for i, c in enumerate(items):
                if c.id == commitment_id:
                    removed = items.pop(i)
                    self._write(items)
                    return removed
        return None

    def prune_done(self, keep: int = 50) -> int:
        """Trim the oldest done items beyond ``keep``. Returns how many were removed."""
        with self._lock:
            items = self.entries()
            done = [c for c in items if c.is_done]
            if len(done) <= keep:
                return 0
            drop = {id(c) for c in done[: len(done) - keep]}
            kept = [c for c in items if id(c) not in drop]
            self._write(kept)
            return len(items) - len(kept)

    def _write(self, items: list[Commitment]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [_HEADER, ""]
        for c in items:
            lines.append(c.to_line())
            lines.extend(c.step_lines())
        data = "\n".join(lines) + "\n"
        # Atomic: write to a temp file in the same dir, then replace. A crash
        # leaves either the old file or the new one — never a half-written ledger.
        tmp = self.path.with_suffix(".md.tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, self.path)

    # --- prompting ---------------------------------------------------------

    def render_for_prompt(self) -> str:
        """A compact block of open commitments for the system prompt."""
        items = self.open_items()
        if not items:
            return (
                "\n\nLEDGER: No open commitments are tracked right now. If the user mentions "
                "something they owe, await, or must do by a date, offer to track it "
                "(propose_commitment — show the suggested steps for the user to confirm)."
            )
        lines = []
        for c in items:
            tags = [c.kind]
            if c.owner == "other":
                tags.append("waiting on them")
            if c.status in ("waiting", "blocked"):
                tags.append(c.status)
            if not c.remind:
                tags.append("reminders off")
            suffix = f" [{', '.join(tags)}]" if tags else ""
            due = f" — due {c.due}" if c.due else ""
            prog = ""
            if c.progress is not None:
                done_n, total = c.progress
                prog = f" ({done_n}/{total})"
            lines.append(f"- ({c.id}) {c.text}{due}{prog}{suffix}")
            # Surface open steps so Aurora can chase / tick the right one.
            for s in c.steps:
                if not s.done:
                    lines.append(f"    ☐ {s.text}")
        return (
            "\n\nLEDGER — open commitments you're tracking for the user. Use update_commitment / "
            "mark_done by id as things progress; reference these when relevant. For checklist "
            "items, tick a step ONLY with suggest_step_done (suggest-and-confirm, never silent), "
            "and mark_done asks before closing while steps remain:\n"
            + "\n".join(lines)
        )
