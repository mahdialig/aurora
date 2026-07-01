"""File-backed procedural playbooks — Aurora's "how-to" memory.

The third memory layer (alongside :class:`~aurora.memory.store.MemoryStore` facts and
:class:`~aurora.profile.store.ProfileStore` preferences): reusable **step templates for
recurring workflows**. Where a commitment's checklist is a one-off definition of done,
a playbook is the *knowledge that fills it* the next time the same kind of task shows
up — e.g. "for withholding tax, sending the bukti potong is step 1; **paying DJP** is
the real done" (the D20/D21 motivating example).

It is a plain markdown file the user can read and edit by hand
(``data/playbook/playbooks.md``), one ``##`` block per playbook::

    # Aurora's playbooks — step templates for recurring workflows

    ## withholding-tax · on:2026-07-01 src:you told me
    trigger: bukti potong, pph, withholding tax
    - Prepare the bukti potong
    - Send the bukti potong to the counterparty
    - Pay DJP and keep the payment proof
    notes: A counterparty confirming receipt is NOT done — paying DJP is.

The ``## <name>`` heading is a stable slug; the trailing ``key:val`` block after ``·``
is provenance. ``trigger:`` is a comma-separated list of keywords used to match the
playbook to a task; ``- `` lines are the ordered steps; ``notes:`` is optional guidance.

Like the profile and the ledger, writes are **keyed** (``set`` upserts by name, so a
correction updates in place and forgetting truly reverts, D8), **atomic** (tmp +
``os.replace``), and lock-guarded so a crash never corrupts the file.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_HEADER = "# Aurora's playbooks — step templates for recurring workflows"

_SEP = " · "
# One key:val provenance token (dates/sources never contain spaces).
_KV_RE = re.compile(r"(?P<key>[a-z_]+):(?P<val>\S+)")


@dataclass(frozen=True)
class Playbook:
    """One recurring workflow and the steps that define its "done"."""

    name: str                                       # stable slug, e.g. "withholding-tax"
    steps: tuple[str, ...] = ()                     # ordered definition-of-done steps
    triggers: tuple[str, ...] = ()                  # keywords that match a task to this
    notes: str = ""                                 # optional guidance
    on: str = ""                                    # ISO date set
    source: str = ""                                # provenance

    def to_lines(self) -> list[str]:
        head = f"## {self.name}"
        meta = []
        if self.on:
            meta.append(f"on:{self.on}")
        if self.source:
            meta.append(f"src:{self.source}")
        if meta:
            head += _SEP + " ".join(meta)
        lines = [head]
        if self.triggers:
            lines.append("trigger: " + ", ".join(self.triggers))
        lines.extend(f"- {s}" for s in self.steps)
        if self.notes:
            lines.append(f"notes: {self.notes}")
        return lines


class PlaybookStore:
    """Reads/writes the playbooks markdown file under ``<data_dir>/playbook``."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "playbook" / "playbooks.md"
        self._lock = threading.Lock()

    # --- reading -----------------------------------------------------------

    def playbooks(self) -> list[Playbook]:
        if not self.path.exists():
            return []
        out: list[Playbook] = []
        cur: dict | None = None

        def flush() -> None:
            if cur and cur["name"]:
                out.append(
                    Playbook(
                        name=cur["name"],
                        steps=tuple(cur["steps"]),
                        triggers=tuple(cur["triggers"]),
                        notes=cur["notes"],
                        on=cur["on"],
                        source=cur["source"],
                    )
                )

        for raw in self.path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("## "):
                flush()
                body = line[3:].strip()
                left, sep, meta = body.partition(_SEP)
                prov = {m.group("key"): m.group("val") for m in _KV_RE.finditer(meta)} if sep else {}
                cur = {
                    "name": left.strip(),
                    "steps": [],
                    "triggers": [],
                    "notes": "",
                    "on": prov.get("on", ""),
                    "source": prov.get("src", ""),
                }
            elif cur is None:
                continue  # ignore the file header / preamble
            elif line.lower().startswith("trigger:"):
                cur["triggers"] = [t.strip() for t in line.split(":", 1)[1].split(",") if t.strip()]
            elif line.lower().startswith("notes:"):
                cur["notes"] = line.split(":", 1)[1].strip()
            elif line.startswith("- "):
                step = line[2:].strip()
                if step:
                    cur["steps"].append(step)
        flush()
        return out

    def get(self, name: str) -> Playbook | None:
        name = name.strip().lower()
        for p in self.playbooks():
            if p.name.lower() == name:
                return p
        return None

    def match(self, text: str) -> Playbook | None:
        """Best-effort: the first playbook whose name or a trigger keyword appears in
        ``text`` (case-insensitive). Used to seed a matching task's steps."""
        hay = (text or "").lower()
        if not hay.strip():
            return None
        for p in self.playbooks():
            needles = [p.name.lower(), p.name.replace("-", " ").lower(), *(t.lower() for t in p.triggers)]
            if any(n and n in hay for n in needles):
                return p
        return None

    def names(self) -> list[str]:
        return [p.name for p in self.playbooks()]

    def is_empty(self) -> bool:
        return not self.playbooks()

    # --- writing -----------------------------------------------------------

    def set(
        self,
        name: str,
        *,
        steps: list[str],
        triggers: list[str] | None = None,
        notes: str = "",
        source: str = "you told me",
    ) -> Playbook:
        """Upsert a playbook by name — replaces one with the same name, else appends."""
        name = name.strip()
        steps = [s.strip() for s in (steps or []) if s.strip()]
        if not name:
            raise ValueError("A playbook needs a name.")
        if not steps:
            raise ValueError("A playbook needs at least one step.")
        new = Playbook(
            name=name,
            steps=tuple(steps),
            triggers=tuple(t.strip() for t in (triggers or []) if t.strip()),
            notes=notes.strip(),
            on=date.today().isoformat(),
            source=source.strip(),
        )
        with self._lock:
            items = self.playbooks()
            out: list[Playbook] = []
            replaced = False
            for p in items:
                if p.name.lower() == name.lower():
                    out.append(new)
                    replaced = True
                else:
                    out.append(p)
            if not replaced:
                out.append(new)
            self._write(out)
        return new

    def remove(self, name: str) -> Playbook | None:
        """Drop a playbook by name. Forgetting truly reverts behavior (D8)."""
        name = name.strip().lower()
        with self._lock:
            items = self.playbooks()
            for i, p in enumerate(items):
                if p.name.lower() == name:
                    removed = items.pop(i)
                    self._write(items)
                    return removed
        return None

    def _write(self, items: list[Playbook]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [_HEADER, ""]
        for p in items:
            lines.extend(p.to_lines())
            lines.append("")
        data = "\n".join(lines).rstrip("\n") + "\n"
        tmp = self.path.with_suffix(".md.tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, self.path)

    # --- prompting ---------------------------------------------------------

    def render_for_prompt(self) -> str:
        """The playbooks block for the system prompt."""
        items = self.playbooks()
        if not items:
            return (
                "\n\nPLAYBOOKS: You don't have any saved workflow playbooks yet. When the user "
                "says 'save this as a playbook' or describes what they do 'whenever'/'every time' "
                "something happens, call propose_playbook (NOT propose_commitment) to save that "
                "reusable workflow so you get the steps right next time."
            )
        blocks = []
        for p in items:
            head = f"- {p.name}"
            if p.triggers:
                head += f" (when: {', '.join(p.triggers)})"
            step_lines = "\n".join(f"    · {s}" for s in p.steps)
            block = f"{head}\n{step_lines}"
            if p.notes:
                block += f"\n    note: {p.notes}"
            blocks.append(block)
        return (
            "\n\nPLAYBOOKS — step templates for recurring workflows. When a task the user "
            "asks you to track matches one of these, propose it (via propose_commitment) with "
            "these steps as the definition of done, adapting the wording to the specifics. When "
            "the user instead says 'save this as a playbook' or describes what they do "
            "'whenever'/'every time' X happens, call propose_playbook (NOT propose_commitment) to "
            "save a new reusable workflow:\n"
            + "\n".join(blocks)
        )


__all__ = ["Playbook", "PlaybookStore"]
