"""The proactive poller — notices new mail and pings the user.

A dependency-free asyncio loop (python-telegram-bot's JobQueue needs APScheduler,
which isn't installed). ``poll_once`` is the testable core: it takes explicit
dependencies and an injected ``notify`` callback, so it can be exercised with fakes
and no network. ``start_notifier`` wires it to a running PTB ``Application``.
"""

from __future__ import annotations

import asyncio
import logging
from email.utils import parseaddr

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from aurora.llm.client import Message
from aurora.notify.classifier import Verdict, classify_new
from aurora.notify.state import NotifyState

logger = logging.getLogger("aurora.notify")

_LIST_LIMIT = 15      # how many unread to scan per account per poll
_NOTIFY_CAP = 6       # max pings per cycle (avoid floods after long downtime)


def _stash_commitment(application, payload: dict) -> str:
    """Stash a proposed commitment server-side, returning a short callback token.

    Mirrors the surface's ``_stash`` (callback_data is too small for the payload),
    sharing the ``pending_seq`` counter so tokens never collide across buckets.
    """
    store = application.bot_data.setdefault("pending_commitments", {})
    seq = application.bot_data.get("pending_seq", 0) + 1
    application.bot_data["pending_seq"] = seq
    token = str(seq)
    store[token] = payload
    return token


def _sender_name(sender: str) -> str:
    name, addr = parseaddr(sender or "")
    return name.strip() or addr.strip() or (sender or "someone")


def format_notification(account: str, summary, verdict: Verdict) -> str:
    """Render the user-facing notification line for one email."""
    who = _sender_name(summary.sender)
    head = verdict.headline or summary.subject or "new email"
    if verdict.decision == "ask":
        return (
            f"📬 New from {who} ({account}): “{summary.subject}”. "
            f"Not sure this matters to you — want me to keep flagging these, or skip them?"
        )
    return f"📬 New from {who} ({account}): {head}"


async def poll_once(accounts, state: NotifyState, llm, memory, notify, *, limit: int = _LIST_LIMIT) -> None:
    """One sweep: scan each account for new mail, classify it, ping what matters.

    ``notify`` is an async callable ``(text, meta|None) -> None``. ``meta`` is a small
    dict describing the email (for conversational follow-up context), or None for the
    "…and N more" summary line.
    """
    for name, acc in accounts.resolve("all"):
        try:
            summaries = await asyncio.to_thread(acc.list_unread, limit)
        except Exception:  # noqa: BLE001 - a flaky mailbox shouldn't kill the loop
            logger.exception("Notifier: list_unread failed for %s", name)
            continue

        ids = [s.id for s in summaries]
        if state.is_first_contact(name):
            state.mark_seen(name, ids)  # seed silently; no startup flood
            continue

        new_ids = set(state.unseen(name, ids))
        if not new_ids:
            continue
        new_summaries = [s for s in summaries if s.id in new_ids]

        items = [
            {"id": s.id, "account": name, "from": s.sender, "subject": s.subject, "snippet": s.snippet}
            for s in new_summaries
        ]
        memory_text = memory.render_for_prompt() if memory else ""
        try:
            verdicts = await asyncio.to_thread(classify_new, llm, items, memory_text)
        except Exception:  # noqa: BLE001
            logger.exception("Notifier: classification failed for %s", name)
            verdicts = [Verdict(id=s.id, decision="notify", headline=s.subject) for s in new_summaries]

        by_id = {s.id: s for s in new_summaries}
        to_send = [v for v in verdicts if v.decision in ("notify", "ask") and v.id in by_id]

        for i, v in enumerate(to_send):
            if i >= _NOTIFY_CAP:
                await notify(f"📬 …and {len(to_send) - _NOTIFY_CAP} more new email(s) in {name}.", None)
                break
            s = by_id[v.id]
            meta = {
                "account": name,
                "email_id": s.id,
                "from": s.sender,
                "subject": s.subject,
                "decision": v.decision,
                "commitment": v.commitment,
            }
            await notify(format_notification(name, s, v), meta)

        # Mark EVERYTHING scanned this cycle as seen — including skipped/notified —
        # so nothing re-triggers next poll.
        state.mark_seen(name, ids)


def start_notifier(application) -> None:
    """Begin the background poll loop on the running Application (call from post_init)."""
    config = application.bot_data["config"]
    accounts = application.bot_data["mail_accounts"]
    llm = application.bot_data["llm"]
    memory = application.bot_data["memory"]
    uid = config.allowed_user_id
    state = NotifyState(config.data_dir)
    application.bot_data["notify_state"] = state

    async def notify(text: str, meta: dict | None) -> None:
        # When the email implies an open loop, offer a one-tap "Track this" button.
        reply_markup = None
        if meta and meta.get("commitment"):
            token = _stash_commitment(
                application,
                {
                    "text": meta["commitment"],
                    "source": f"email:{meta['account']}:{meta['email_id']}",
                },
            )
            reply_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("➕ Track this", callback_data=f"track:{token}"),
                        InlineKeyboardButton("Dismiss", callback_data=f"untrack:{token}"),
                    ]
                ]
            )
        await application.bot.send_message(chat_id=uid, text=text, reply_markup=reply_markup)
        # Thread it into the user's conversation so follow-up ("that's important") has context.
        history = application.chat_data[uid].setdefault("history", [])
        history.append(Message("assistant", text))
        del history[:-40]
        if meta is not None:
            recents = application.bot_data.setdefault("recent_notifications", [])
            recents.append(meta)
            del recents[:-5]

    async def loop() -> None:
        interval = config.notify_interval_seconds
        logger.info("Notifier started (every %ss, accounts=%s).", interval, accounts.names())
        while True:
            try:
                await poll_once(accounts, state, llm, memory, notify)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - never let a bad cycle stop the loop
                logger.exception("Notifier poll cycle failed")
            await asyncio.sleep(interval)

    task = asyncio.create_task(loop())
    application.bot_data["notify_task"] = task


def stop_notifier(application) -> None:
    """Cancel the background poll loop (call from post_shutdown)."""
    task = application.bot_data.get("notify_task")
    if task is not None:
        task.cancel()
