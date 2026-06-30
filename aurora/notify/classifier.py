"""Decide which new emails are worth interrupting the user for.

A single batched LLM call per poll: given the user's learned notification
preferences (their memory) and the batch of new-mail summaries, classify each as
``notify`` (ping now), ``ask`` (unsure — ask if it matters), or ``skip`` (stay
silent). Default posture is smart-filter + ask; when the model can't be parsed we
fall back to ``notify`` for everything so mail is never silently dropped.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from aurora.llm.client import Message

logger = logging.getLogger("aurora.notify")

_DECISIONS = {"notify", "ask", "skip"}

_SYSTEM = (
    "You are the notification filter for Aurora, a personal assistant. The user has delegated "
    "their inbox to her and does NOT want to be interrupted for unimportant mail. For each NEW "
    "email, decide one of:\n"
    "- 'notify': clearly worth knowing now (a real person needing something, deadlines, money, "
    "security, anything time-sensitive or personal).\n"
    "- 'skip': obvious noise (bulk newsletters, promotions, automated notifications, no-reply "
    "blasts) — stay silent.\n"
    "- 'ask': genuinely unsure whether THIS user cares — Aurora will ask if it matters.\n"
    "Respect the user's stated preferences below; they override your defaults. Be calm and "
    "conservative: when something is plainly promotional, 'skip'; reserve 'ask' for real "
    "uncertainty.\n"
    "If (and only if) the email implies a concrete open loop the user shouldn't drop — they owe a "
    "reply, there's a deadline, or an action is requested of them — add a short 'commitment' phrase "
    "describing it (e.g. 'Reply to Sara about the proposal', 'Pay invoice by Jul 10'). Otherwise "
    "leave 'commitment' as an empty string. Newsletters/promos/automated mail never have a commitment.\n"
    "Reply with ONLY a JSON array, one object per email, in the same order, each: "
    '{"id": "<id>", "decision": "notify|ask|skip", "headline": "<≤12-word gist>", '
    '"reason": "<short why>", "commitment": "<short open-loop phrase or empty>"}. '
    "No prose, no code fences."
)


@dataclass(frozen=True)
class Verdict:
    """The filter's call on one email."""

    id: str
    decision: str  # 'notify' | 'ask' | 'skip'
    headline: str
    reason: str = ""
    commitment: str = ""  # an open loop this email implies, or "" — for one-tap tracking


def build_prompt(items: list[dict], memory_text: str) -> list[Message]:
    """Assemble the (system, user) messages for the classifier."""
    prefs = memory_text.strip() or "(none recorded yet)"
    lines = [f"USER'S NOTIFICATION PREFERENCES:\n{prefs}", "", "NEW EMAILS:"]
    for it in items:
        lines.append(
            json.dumps(
                {
                    "id": str(it.get("id", "")),
                    "account": it.get("account", ""),
                    "from": it.get("from") or it.get("sender", ""),
                    "subject": it.get("subject", ""),
                    "snippet": it.get("snippet", ""),
                },
                ensure_ascii=False,
            )
        )
    return [Message("system", _SYSTEM), Message("user", "\n".join(lines))]


def _extract_json_array(text: str) -> list:
    """Best-effort pull of a JSON array out of a model reply (tolerates fences/prose)."""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON array found")
    return json.loads(text[start : end + 1])


def _fallback(items: list[dict]) -> list[Verdict]:
    """When parsing fails, notify about everything rather than drop mail silently."""
    return [
        Verdict(id=str(it.get("id", "")), decision="notify", headline=it.get("subject", "") or "New email")
        for it in items
    ]


def classify_new(llm, items: list[dict], memory_text: str) -> list[Verdict]:
    """Classify a batch of new emails. Returns one Verdict per item (best-effort)."""
    if not items:
        return []
    try:
        raw = llm.complete(build_prompt(items, memory_text), temperature=0.2)
        parsed = _extract_json_array(raw)
    except Exception:  # noqa: BLE001 - any LLM/parse failure → safe fallback
        logger.exception("Classifier failed; defaulting to notify-all.")
        return _fallback(items)

    by_id = {str(it.get("id", "")): it for it in items}
    out: list[Verdict] = []
    seen: set[str] = set()
    for obj in parsed if isinstance(parsed, list) else []:
        if not isinstance(obj, dict):
            continue
        vid = str(obj.get("id", ""))
        if vid not in by_id or vid in seen:
            continue
        decision = str(obj.get("decision", "")).lower().strip()
        if decision not in _DECISIONS:
            decision = "notify"
        seen.add(vid)
        out.append(
            Verdict(
                id=vid,
                decision=decision,
                headline=(obj.get("headline") or by_id[vid].get("subject", "") or "New email").strip(),
                reason=(obj.get("reason") or "").strip(),
                commitment=(obj.get("commitment") or "").strip(),
            )
        )
    # Any emails the model omitted → notify (never silently drop).
    for vid, it in by_id.items():
        if vid not in seen:
            out.append(Verdict(id=vid, decision="notify", headline=it.get("subject", "") or "New email"))
    return out
