"""Revise a proposed commitment's checklist from a free-text instruction.

When Aurora proposes a task with candidate steps (the capture proposal card), the
user can tap "✏️ Yes, but adjust" and tell her what to change in plain language —
drop/add/rename a step, change the due, or collapse the whole thing to a single
item. :func:`revise_steps` applies that instruction to the proposal payload via one
light LLM call.

Mirrors :func:`aurora.profile.interview.distill` and ``brief.compose``: on ANY
failure it returns the payload unchanged, so the adjust loop never breaks because
the model hiccuped — the user can just rephrase or tap a button.
"""

from __future__ import annotations

import json
import logging

from aurora.llm.client import Message

logger = logging.getLogger("aurora.ledger")

_REVISE_SYSTEM = (
    "You edit a proposed to-do and its checklist of definition-of-done steps based on "
    "the user's instruction. The user owns the granularity: do EXACTLY what they ask — "
    "drop, add, rename, or reorder steps; change the due date/time; or collapse to a "
    "single step if they say things like 'just track it as one item'. Keep everything "
    "else as-is. Preserve the user's meaning; don't invent steps they didn't imply.\n"
    "Reply with ONLY a JSON object: {\"text\": <task title>, \"due\": <ISO date or "
    "date+time like 2026-07-03T17:00, or empty string>, \"steps\": [<step text>, ...]}. "
    "An empty steps list means a flat single-item task. No prose, no code fences."
)


def revise_steps(llm, payload: dict, instruction: str) -> dict:
    """Apply a free-text edit to a proposal payload, returning a new payload.

    ``payload`` keys: text, kind, owner, due, steps (list of step texts), source.
    Only text/due/steps are revised; kind/owner/source pass through unchanged."""
    instruction = (instruction or "").strip()
    if not instruction:
        return payload
    current = {
        "text": payload.get("text", ""),
        "due": payload.get("due", ""),
        "steps": list(payload.get("steps") or []),
    }
    try:
        messages = [
            Message("system", _REVISE_SYSTEM),
            Message(
                "user",
                "Current proposal:\n"
                + json.dumps(current, ensure_ascii=False)
                + f"\n\nInstruction: {instruction}",
            ),
        ]
        out = llm.complete(messages, temperature=0.2).strip()
        data = json.loads(_strip_fences(out))
    except Exception:  # noqa: BLE001 - never let a revision break the adjust loop
        logger.exception("Step revision failed; keeping the proposal unchanged.")
        return payload

    revised = dict(payload)
    if isinstance(data.get("text"), str) and data["text"].strip():
        revised["text"] = data["text"].strip()
    if isinstance(data.get("due"), str):
        revised["due"] = data["due"].strip()
    if isinstance(data.get("steps"), list):
        revised["steps"] = [str(s).strip() for s in data["steps"] if str(s).strip()]
    return revised


def _strip_fences(text: str) -> str:
    """Tolerate a ```json … ``` wrapper around the model's reply."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
    return t.strip()


__all__ = ["revise_steps"]
