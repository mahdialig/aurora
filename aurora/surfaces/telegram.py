"""Telegram surface — Aurora as a conversational agent.

A message goes to the agent loop (LLM + memory + tools). Aurora may use tools
(e.g. read/search email across the connected accounts) to answer, and reports in
her own words — she is a delegate, not a viewer. Actions that leave a mailbox are
approval-gated (added in stage 4). Access is restricted to the single allowed user.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from aurora.activity import ActivityLog
from aurora.agent import run_agent
from aurora.brief.compose import build_brief
from aurora.config import Config, ConfigError
from aurora.ledger import LedgerStore
from aurora.llm import DeepSeekClient, LLMClient, Message
from aurora.memory import MemoryStore
from aurora.notify.job import start_notifier, stop_notifier
from aurora.profile import QUESTIONS, ProfileStore, distill
from aurora.schedule import start_scheduler, stop_scheduler
from aurora.schedule.runner import resolve_tz
from aurora.sources.base import Reply
from aurora.sources.registry import MailAccounts, build_mail_accounts
from aurora.tools.email_tools import build_email_tools
from aurora.tools.ledger_tools import build_ledger_tools
from aurora.tools.notify_tools import build_notify_tools

logger = logging.getLogger("aurora.telegram")

# Aurora's base voice. Email capability + current memory are appended at call time.
SYSTEM_PROMPT = (
    "You are Aurora, a calm, concise personal assistant. "
    "You help the user declutter their digital life and never let them miss a thing. "
    "Keep replies short and warm. "
    "If the user shares a durable new fact or preference about themselves that is "
    "NOT already in your memory below, append on a final new line a marker in EXACTLY "
    "this format: [[REMEMBER: <the fact, concise and first-person>]]. "
    "The app turns that marker into a button — do NOT mention it, explain it, or ask the "
    "user to type anything. Emit at most one marker per reply, and none if nothing is new. "
    "Never claim you have saved anything yourself; saving only happens when the user confirms."
)

# How many recent messages of short-term (in-session) conversation to keep and
# re-send each turn. Long-term memory persists separately via MemoryStore.
MAX_HISTORY_MESSAGES = 20

# Aurora emits this hidden marker to propose a memory; the bot turns it into a button.
REMEMBER_MARKER_RE = re.compile(r"\[\[REMEMBER:\s*(?P<fact>.+?)\]\]", re.IGNORECASE | re.DOTALL)


def parse_remember_marker(reply: str) -> tuple[str, str | None]:
    """Split an LLM reply into (visible_text, proposed_fact_or_None)."""
    match = REMEMBER_MARKER_RE.search(reply)
    if not match:
        return reply.strip(), None
    fact = match.group("fact").strip()
    visible = REMEMBER_MARKER_RE.sub("", reply).strip()
    return visible, (fact or None)


def _allowed_only(handler):
    """Wrap a handler so only the configured user id is served."""

    async def guarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
        config: Config = context.application.bot_data["config"]
        user = update.effective_user
        if user is None or user.id != config.allowed_user_id:
            uid = "unknown" if user is None else user.id
            logger.warning("Rejected message from non-allowed user id=%s", uid)
            if update.effective_message:
                await update.effective_message.reply_text(
                    "This is a private assistant and you're not its owner."
                )
            return
        return await handler(update, context)

    return guarded


# --------------------------------------------------------------------------- #
# Simple commands
# --------------------------------------------------------------------------- #


@_allowed_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    memory: MemoryStore = context.application.bot_data["memory"]
    profile: ProfileStore = context.application.bot_data["profile"]
    pref = profile.get("preferred_name")
    name = (pref.value if pref else None) or memory.display_name() or update.effective_user.first_name
    nudge = (
        " New here? /onboard sets up how I work for you. /help lists everything I can do."
        if profile.is_empty()
        else " /help lists everything I can do; /profile shows your preferences."
    )
    await update.effective_message.reply_text(
        f"Hi {name} — Aurora here. Just talk to me: ask what's new in your email, ask me to "
        "reply to someone, or tell me things to remember." + nudge
    )


HELP_TEXT = (
    "Just talk to me — ask what's new in your email, ask me to reply to someone, or tell me "
    "things to remember. Commands:\n"
    "\n*Getting set up*\n"
    "/onboard — set up how I work for you (a few quick questions)\n"
    "/profile — show your preferences · /profile forget <key> — clear one\n"
    "\n*Email & staying on top of things*\n"
    "/inbox — what's worth knowing in your unread mail\n"
    "/brief — your daily brief on demand\n"
    "/agenda (/waiting) — open commitments I'm tracking\n"
    "/track <thing> — track a commitment · /done <id> — mark it done\n"
    "\n*What I remember*\n"
    "/remember <text> — save a fact · /memory — list them · /forget <n|text> — drop one\n"
    "\n*Housekeeping*\n"
    "/new — clear our recent chat (keeps what I've learned)\n"
    "/whoami — your Telegram id · /help — this list"
)


@_allowed_only
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — list what Aurora can do."""
    await update.effective_message.reply_text(HELP_TEXT, parse_mode="Markdown")


@_allowed_only
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(f"Your Telegram user id is {update.effective_user.id}.")


@_allowed_only
async def remember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/remember <text> — store a durable fact or preference."""
    memory: MemoryStore = context.application.bot_data["memory"]
    text = " ".join(context.args).strip() if context.args else ""
    if not text:
        await update.effective_message.reply_text(
            "Tell me what to remember, e.g. /remember I prefer concise replies."
        )
        return
    entry = memory.add(text)
    await update.effective_message.reply_text(f"Got it — I'll remember: {entry.text}")


@_allowed_only
async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/memory — list what Aurora currently knows."""
    memory: MemoryStore = context.application.bot_data["memory"]
    items = memory.entries()
    if not items:
        await update.effective_message.reply_text(
            "I don't know anything about you yet. Use /remember to teach me."
        )
        return
    lines = [f"{i}. {entry.text}" for i, entry in enumerate(items, start=1)]
    await update.effective_message.reply_text("Here's what I remember:\n" + "\n".join(lines))


@_allowed_only
async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/forget <index|text> — drop a memory."""
    memory: MemoryStore = context.application.bot_data["memory"]
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.effective_message.reply_text(
            "Tell me what to forget — a number from /memory, or some words to match."
        )
        return
    removed = memory.forget(query)
    if removed is None:
        await update.effective_message.reply_text("I couldn't find a matching memory to forget.")
    else:
        await update.effective_message.reply_text(f"Forgotten: {removed.text}")


@_allowed_only
async def new_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/new — clear the short-term conversation thread (keeps long-term memory)."""
    context.chat_data["history"] = []
    await update.effective_message.reply_text(
        "Fresh start — I've cleared our recent chat. I still remember what you've taught me."
    )


@_allowed_only
async def brief_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/brief — compose and send the daily brief on demand."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    # build_brief does blocking I/O + an LLM call — keep it off the event loop.
    text = await asyncio.to_thread(build_brief, context.application, weekly=False)
    await update.effective_message.reply_text(
        text or "Nothing pressing right now — your plate's clear. 🌤️"
    )


@_allowed_only
async def agenda_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/agenda (alias /waiting) — show open commitments Aurora is tracking."""
    ledger: LedgerStore = context.application.bot_data["ledger"]
    items = ledger.open_items()
    if not items:
        await update.effective_message.reply_text(
            "Nothing on your plate that I'm tracking. Tell me what to track, or /track <thing>."
        )
        return
    lines = []
    for c in items:
        due = f" — due {c.due}" if c.due else ""
        tag = " (waiting on them)" if c.owner == "other" else ""
        flag = f" [{c.status}]" if c.status in ("waiting", "blocked") else ""
        lines.append(f"• {c.id}: {c.text}{due}{tag}{flag}")
    await update.effective_message.reply_text("Here's what's open:\n" + "\n".join(lines))


@_allowed_only
async def track_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/track <text> — quickly add a commitment."""
    ledger: LedgerStore = context.application.bot_data["ledger"]
    text = " ".join(context.args).strip() if context.args else ""
    if not text:
        await update.effective_message.reply_text("What should I track? e.g. /track reply to Sara by Friday")
        return
    c = ledger.add(text, source="chat")
    await update.effective_message.reply_text(f"Tracking ({c.id}): {c.text}")


@_allowed_only
async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/done <id> — mark a tracked commitment complete."""
    ledger: LedgerStore = context.application.bot_data["ledger"]
    cid = " ".join(context.args).strip() if context.args else ""
    if not cid:
        await update.effective_message.reply_text("Which one? Give me its id, e.g. /done c3 (see /agenda).")
        return
    done = ledger.mark_done(cid)
    if done is None:
        await update.effective_message.reply_text(f"I couldn't find a commitment with id {cid}. Check /agenda.")
    else:
        await update.effective_message.reply_text(f"Done ✅: {done.text}")


# --------------------------------------------------------------------------- #
# /onboard — the week-1 EA interview that seeds the preference profile
# --------------------------------------------------------------------------- #


def _profile_listing(profile: ProfileStore) -> str:
    items = profile.fields()
    if not items:
        return "(nothing saved yet)"
    return "\n".join(f"• {f.key.replace('_', ' ')}: {f.value}" for f in items)


def _onboard_options(context: ContextTypes.DEFAULT_TYPE, question) -> list[tuple[str, str]]:
    """Preset (button label, value) pairs for a question, plus any dynamic ones."""
    options = list(question.options)
    if question.key == "preferred_name":
        memory: MemoryStore = context.application.bot_data["memory"]
        known = memory.display_name()
        if known:
            options = [(known, known), *options]
    return options


async def _onboard_send_question(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    state = context.chat_data["onboarding"]
    idx = state["idx"]
    question = QUESTIONS[idx]
    rows = [
        [InlineKeyboardButton(label, callback_data=f"onb:pick:{i}")]
        for i, (label, _value) in enumerate(_onboard_options(context, question))
    ]
    rows.append(
        [
            InlineKeyboardButton("⏭ Skip", callback_data="onb:skip"),
            InlineKeyboardButton("✖ Stop", callback_data="onb:stop"),
        ]
    )
    text = f"({idx + 1}/{len(QUESTIONS)}) {question.label}"
    text += f"\n{question.hint}" if question.hint else "\n(Tap an option, or just type your own answer.)"
    state["awaiting"] = "answer"
    state["pending"] = None
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(rows))


async def _onboard_send_confirm(context: ContextTypes.DEFAULT_TYPE, chat_id: int, value: str) -> None:
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Save", callback_data="onb:save"),
                InlineKeyboardButton("✏️ Edit", callback_data="onb:edit"),
                InlineKeyboardButton("⏭ Skip", callback_data="onb:skip"),
            ]
        ]
    )
    await context.bot.send_message(
        chat_id=chat_id, text=f"I'll note: {value}\nLooks right?", reply_markup=keyboard
    )


async def _onboard_begin(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    context.chat_data["onboarding"] = {"active": True, "idx": 0, "awaiting": "answer", "pending": None}
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "Let's set up how I work for you — a few quick questions so I can tailor what I "
            "flag, how I draft your email, and when I leave you alone. Tap an option or type "
            "your own; ⏭ Skip any, ✖ Stop anytime. You can redo this with /onboard later."
        ),
    )
    await _onboard_send_question(context, chat_id)


async def _onboard_advance(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    state = context.chat_data.get("onboarding")
    if not state:
        return
    state["idx"] += 1
    if state["idx"] >= len(QUESTIONS):
        await _onboard_finish(context, chat_id)
    else:
        await _onboard_send_question(context, chat_id)


async def _onboard_finish(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    context.chat_data.pop("onboarding", None)
    profile: ProfileStore = context.application.bot_data["profile"]
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "All set — thank you. Here's what I've got:\n\n"
            + _profile_listing(profile)
            + "\n\nI'll work to these from now on. Change anything anytime: re-run /onboard, "
            "or /profile forget <key>."
        ),
    )


async def _onboard_handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """A typed message during onboarding — treat it as the answer to the current question."""
    state = context.chat_data["onboarding"]
    question = QUESTIONS[state["idx"]]
    llm: LLMClient = context.application.bot_data["llm"]
    chat_id = update.effective_chat.id
    text = (text or "").strip()
    if not text:
        await update.effective_message.reply_text("Type your answer, or tap ⏭ Skip / ✖ Stop.")
        return
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    # distill does one LLM call (with raw-text fallback) — keep it off the event loop.
    value = await asyncio.to_thread(distill, llm, question, text)
    state["pending"] = value
    state["awaiting"] = "confirm"
    await _onboard_send_confirm(context, chat_id, value)


@_allowed_only
async def onboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/onboard — run (or re-run) the preference interview."""
    profile: ProfileStore = context.application.bot_data["profile"]
    if not profile.is_empty():
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔄 Re-run", callback_data="onb:start:rerun"),
                    InlineKeyboardButton("👀 Review", callback_data="onb:start:review"),
                    InlineKeyboardButton("✖ Cancel", callback_data="onb:start:cancel"),
                ]
            ]
        )
        await update.effective_message.reply_text(
            "You've already set up your profile. Re-run the interview, review it, or cancel?",
            reply_markup=keyboard,
        )
        return
    await _onboard_begin(context, update.effective_chat.id)


@_allowed_only
async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/profile — show stored preferences; /profile forget <key> drops one."""
    profile: ProfileStore = context.application.bot_data["profile"]
    args = context.args or []
    if args and args[0].lower() == "forget":
        key = args[1].strip() if len(args) > 1 else ""
        if not key:
            await update.effective_message.reply_text("Which one? e.g. /profile forget reply_tone")
            return
        removed = profile.remove(key)
        if removed is None:
            await update.effective_message.reply_text(
                f"No profile field named '{key}'. Check /profile for the keys."
            )
        else:
            await update.effective_message.reply_text(f"Forgotten: {removed.key} ({removed.value}).")
        return
    if profile.is_empty():
        await update.effective_message.reply_text(
            "Your profile is empty. Run /onboard and I'll learn how you like to work."
        )
        return
    await update.effective_message.reply_text(
        "Your preferences:\n"
        + _profile_listing(profile)
        + "\n\n(/onboard to revise, /profile forget <key> to clear one.)"
    )


@_allowed_only
async def on_onboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Taps inside the onboarding interview (pick / save / edit / skip / stop / start menu)."""
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    chat_id = update.effective_chat.id
    base = query.message.text or ""
    profile: ProfileStore = context.application.bot_data["profile"]

    # The "you've already onboarded" menu — handled before the active-state check.
    if action == "start":
        sub = parts[2] if len(parts) > 2 else ""
        if sub == "cancel":
            await query.edit_message_text(base + "\n\n— okay, maybe later.")
        elif sub == "review":
            await query.edit_message_text(base + "\n\nYour preferences:\n" + _profile_listing(profile))
        elif sub == "rerun":
            await query.edit_message_text(base + "\n\n🔄 Starting over.")
            await _onboard_begin(context, chat_id)
        return

    state = context.chat_data.get("onboarding")
    if not state or not state.get("active"):
        await query.edit_message_text(base + "\n\n(this interview has expired — /onboard to start again)")
        return

    question = QUESTIONS[state["idx"]]

    if action == "pick":
        options = _onboard_options(context, question)
        try:
            _label, value = options[int(parts[2])]
        except (IndexError, ValueError):
            await query.edit_message_text(base + "\n\n(couldn't read that choice — type your answer instead)")
            return
        profile.set(question.key, value, source="onboarding")
        await query.edit_message_text(base + f"\n\n✅ Saved: {value}")
        await _onboard_advance(context, chat_id)
    elif action == "save":
        value = state.get("pending")
        if value:
            profile.set(question.key, value, source="onboarding")
            await query.edit_message_text(base + f"\n\n✅ Saved: {value}")
        else:
            await query.edit_message_text(base + "\n\n(nothing to save — type your answer)")
            return
        await _onboard_advance(context, chat_id)
    elif action == "edit":
        state["awaiting"] = "answer"
        state["pending"] = None
        await query.edit_message_text(base + "\n\n✏️ Okay — type your answer.")
    elif action == "skip":
        await query.edit_message_text(base + "\n\n⏭ Skipped.")
        await _onboard_advance(context, chat_id)
    elif action == "stop":
        await query.edit_message_text(base + "\n\n✖ Stopped — I saved what you'd confirmed so far.")
        await _onboard_finish(context, chat_id)


# --------------------------------------------------------------------------- #
# Pending-action stash (server-side; callback_data is too small for full values)
# --------------------------------------------------------------------------- #


def _stash(context: ContextTypes.DEFAULT_TYPE, bucket: str, value: object) -> str:
    store = context.application.bot_data.setdefault(bucket, {})
    seq = context.application.bot_data.get("pending_seq", 0) + 1
    context.application.bot_data["pending_seq"] = seq
    token = str(seq)
    store[token] = value
    return token


def _stash_pending_fact(context: ContextTypes.DEFAULT_TYPE, fact: str) -> str:
    return _stash(context, "pending_memories", fact)


# --------------------------------------------------------------------------- #
# Conversational agent turn
# --------------------------------------------------------------------------- #


def _email_capability(accounts: MailAccounts) -> str:
    """System-prompt note describing which mailboxes Aurora can act on."""
    names = accounts.names()
    if not names:
        return (
            "\n\nEMAIL: You have email tools, but no mailbox is connected yet. "
            "If the user asks about email, tell them it isn't connected."
        )
    labels = {"personal": "personal Gmail", "work": "work email"}
    listed = ", ".join(f"'{n}' ({labels.get(n, n)})" for n in names)
    return (
        f"\n\nEMAIL: You can read and search the user's mail via tools across: {listed}. "
        "When the user asks about email, USE the tools, then report what matters in your own "
        "words — concise, highlighting what needs attention. Never paste the inbox verbatim or "
        "list every message mechanically; you are a delegate, not an email viewer. "
        "To draft, change, or send a reply, you MUST call reply_to_email with the reply body "
        "(read the email first). To write a brand-NEW email (not a reply), call compose_email "
        "(make sure you have the recipient's address). To re-send a reply you already drafted in "
        "this conversation, call resend_last_draft. NEVER write the reply text directly in chat or ask 'send it?' "
        "in words — those tools are the ONLY way the user can act (they show Send / Save-draft / "
        "Cancel buttons). "
        "Keep email replies CONCISE by default. Follow only the user's CURRENT preferences (in "
        "MEMORY below) and their latest instruction for length and tone — do NOT copy the length "
        "or verbosity of your earlier drafts in this conversation. "
        "FIDELITY: reporting in your own words applies to the FRAMING, never the content. When you "
        "reproduce actual message text — quoting it, reading it back, or confirming what you just "
        "sent or drafted — copy it EXACTLY: never change a word, number, name, or emoji. Altering "
        "even one detail makes the user doubt something went wrong, especially when they're checking "
        "that a message is correct or went through. When confirming an action, restate the exact text "
        "you acted on (use the real draft/message, don't regenerate it from memory). If exactness "
        "might matter, quote verbatim; otherwise summarize without inventing or tweaking specifics."
    )


def _time_note(now: datetime) -> str:
    """Tell the agent the current date/time so she can answer 'what time is it?' and
    reason correctly about relative dates (today, tomorrow, this week) and due dates."""
    # Build the day-of-month without a platform-specific strftime flag (%-d is glibc-only,
    # %#d is Windows-only) so the string is identical on the laptop and the Linux VPS.
    stamp = f"{now.strftime('%A')}, {now.day} {now.strftime('%B %Y, %H:%M')}"
    return (
        "\n\nCURRENT DATE & TIME: "
        + stamp
        + f" ({now.tzname()}). This is the real current time — use it whenever the user asks "
        "the time or date, and for ALL relative-date reasoning (today, tomorrow, this week) and "
        "due dates. Don't guess the date from anything else."
    )


def _recent_notifications_note(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Tell the agent which emails Aurora just pinged about, so reactions resolve."""
    recents = context.application.bot_data.get("recent_notifications") or []
    if not recents:
        return ""
    lines = "\n".join(
        f"- from {r.get('from', '?')} ({r.get('account', '?')}): {r.get('subject', '')}"
        for r in recents[-5:]
    )
    return (
        "\n\nRECENT NOTIFICATIONS you proactively sent (most recent last). If the user reacts to "
        "one ('that's important', 'stop notifying me about these', or answering whether it "
        "matters), call set_notification_rule to remember the lesson, then confirm in one line:\n"
        + lines
    )


async def _respond(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str) -> None:
    """Core turn: run the agent loop (memory + email tools) and reply."""
    llm: LLMClient = context.application.bot_data["llm"]
    memory: MemoryStore = context.application.bot_data["memory"]
    profile: ProfileStore = context.application.bot_data["profile"]
    ledger: LedgerStore = context.application.bot_data["ledger"]
    accounts: MailAccounts = context.application.bot_data["mail_accounts"]
    tools = context.application.bot_data["email_tools"]

    history: list[Message] = context.chat_data.setdefault("history", [])
    history.append(Message("user", user_text))

    tz = context.application.bot_data["tz"]
    system_prompt = (
        SYSTEM_PROMPT
        + _time_note(datetime.now(tz))
        + _email_capability(accounts)
        + _recent_notifications_note(context)
        + profile.render_for_prompt()
        + memory.render_for_prompt()
        + ledger.render_for_prompt()
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages += [m.as_dict() for m in history[-MAX_HISTORY_MESSAGES:]]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        result = run_agent(llm, messages, tools)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        logger.exception("Agent loop failed")
        history.pop()  # don't keep a turn we never answered
        await update.effective_message.reply_text(
            f"Sorry — I couldn't think that through just now ({exc.__class__.__name__})."
        )
        return

    # Aurora wants to take an action (e.g. send a reply) — present it for approval.
    if result.is_action:
        await _propose_action(update, context, result, history)
        return

    text_out = result.text or "…"
    visible, fact = parse_remember_marker(text_out)
    if not visible:
        visible = "Want me to remember that?"

    history.append(Message("assistant", visible))
    if len(history) > MAX_HISTORY_MESSAGES:
        del history[:-MAX_HISTORY_MESSAGES]

    reply_markup = None
    if fact:
        token = _stash_pending_fact(context, fact)
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🧠 Remember this", callback_data=f"remember:{token}"),
                    InlineKeyboardButton("Dismiss", callback_data=f"dismiss:{token}"),
                ]
            ]
        )

    await update.effective_message.reply_text(visible, reply_markup=reply_markup)


@_allowed_only
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free-form chat — Aurora may use tools (e.g. email) as needed."""
    # An onboarding interview in progress claims the next typed message as its answer,
    # before it falls through to the agent loop.
    if context.chat_data.get("onboarding", {}).get("active"):
        await _onboard_handle_text(update, context, update.effective_message.text or "")
        return
    await _respond(update, context, update.effective_message.text or "")


@_allowed_only
async def inbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/inbox — a shortcut: ask Aurora what's worth knowing in unread mail."""
    await _respond(
        update,
        context,
        "Briefly, what's worth knowing in my unread email right now? Just the highlights.",
    )


async def _present_reply(update, context, account_name: str, reply: Reply, history: list[Message]) -> None:
    """Stash a reply, remember it as the last draft, and show the approval buttons."""
    token = _stash(context, "pending_replies", (account_name, reply))
    # Keep the exact draft available for resend_last_draft — but server-side only.
    context.chat_data["last_reply"] = (account_name, reply)

    # IMPORTANT: store only a SHORT note in the conversation thread — never the draft
    # body. Past drafts in-context make Aurora copy their length/style, and that would
    # let a *forgotten* preference keep shaping replies. A forgotten rule must truly go.
    history.append(Message("assistant", f"(I drafted a reply to {reply.to} and showed Send/Save/Cancel.)"))
    if len(history) > MAX_HISTORY_MESSAGES:
        del history[:-MAX_HISTORY_MESSAGES]

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Send", callback_data=f"send:{token}"),
                InlineKeyboardButton("📝 Save draft", callback_data=f"savedraft:{token}"),
                InlineKeyboardButton("✖ Cancel", callback_data=f"cancelreply:{token}"),
            ]
        ]
    )
    await update.effective_message.reply_text(
        f"✍️ Draft reply to {reply.to} ({account_name})\nSubject: {reply.subject}\n\n{reply.body}",
        reply_markup=keyboard,
    )


async def _propose_action(update, context, result, history: list[Message]) -> None:
    """Turn an agent action (reply_to_email / resend_last_draft) into an approval prompt."""
    accounts: MailAccounts = context.application.bot_data["mail_accounts"]
    args = result.action_args or {}

    if result.action_name == "resend_last_draft":
        last = context.chat_data.get("last_reply")
        if not last:
            await update.effective_message.reply_text(
                "I don't have a recent draft to resend — ask me to draft a reply first."
            )
            return
        account_name, reply = last
        await _present_reply(update, context, account_name, reply, history)
        return

    if result.action_name == "compose_email":
        account_name = (args.get("account") or "").strip()
        to = (args.get("to") or "").strip()
        subject = (args.get("subject") or "").strip()
        body = (args.get("body") or "").strip()
        if accounts.get(account_name) is None:
            await update.effective_message.reply_text(
                f"I can't send from '{account_name or '?'}' — that account isn't connected."
            )
            return
        if not to or not body:
            await update.effective_message.reply_text("I couldn't put that email together — try again?")
            return
        fresh = Reply(thread_id="", to=to, subject=subject, body=body)
        await _present_reply(update, context, account_name, fresh, history)
        return

    if result.action_name != "reply_to_email":
        await update.effective_message.reply_text("I'm not able to do that one yet.")
        return

    account_name = (args.get("account") or "").strip()
    email_id = (args.get("email_id") or "").strip()
    body = (args.get("body") or "").strip()
    account = accounts.get(account_name)

    if account is None:
        await update.effective_message.reply_text(
            f"I can't act on '{account_name or '?'}' — that account isn't connected."
        )
        return
    if not email_id or not body:
        await update.effective_message.reply_text("I couldn't put that reply together — try again?")
        return

    try:
        original = account.get_message(email_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_message for reply failed")
        await update.effective_message.reply_text(
            f"Couldn't open that email to reply ({exc.__class__.__name__})."
        )
        return

    await _present_reply(update, context, account_name, Reply.to_message(original, body), history)


@_allowed_only
async def on_reply_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tap on Send / Save draft / Cancel under a drafted reply."""
    query = update.callback_query
    await query.answer()
    action, _, token = (query.data or "").partition(":")

    pending: dict[str, tuple[str, Reply]] = context.application.bot_data.setdefault("pending_replies", {})
    entry = pending.pop(token, None)
    base = query.message.text or ""

    if entry is None:
        await query.edit_message_text(base + "\n\n(this draft expired — just ask me again)")
        return

    account_name, reply = entry
    if action == "cancelreply":
        await query.edit_message_text(base + "\n\n✖ Cancelled — nothing sent.")
        return

    accounts: MailAccounts = context.application.bot_data["mail_accounts"]
    account = accounts.get(account_name)
    if account is None:
        await query.edit_message_text(base + "\n\n⚠ That account is no longer connected.")
        return

    activity: ActivityLog | None = context.application.bot_data.get("activity")
    try:
        if action == "send":
            account.send_reply(reply)
            if activity:
                activity.record(f"Sent an email to {reply.to} ({account_name}): {reply.subject}")
            await query.edit_message_text(base + "\n\n✅ Sent.")
        else:  # savedraft
            account.create_draft(reply)
            if activity:
                activity.record(f"Saved a draft to {reply.to} ({account_name}): {reply.subject}")
            await query.edit_message_text(base + "\n\n📝 Saved to Drafts.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("send/draft failed")
        pending[token] = entry  # let the user retry
        await query.edit_message_text(
            base + f"\n\n⚠ Couldn't complete that ({exc.__class__.__name__}). Try the button again."
        )


@_allowed_only
async def on_memory_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle taps on the Remember / Dismiss buttons."""
    query = update.callback_query
    await query.answer()  # stop Telegram's loading spinner

    action, _, token = (query.data or "").partition(":")
    pending: dict[str, str] = context.application.bot_data.setdefault("pending_memories", {})
    fact = pending.pop(token, None)
    base = query.message.text or ""

    if fact is None:
        await query.edit_message_text(base + "\n\n(that suggestion has expired)")
        return

    if action == "remember":
        memory: MemoryStore = context.application.bot_data["memory"]
        memory.add(fact)
        await query.edit_message_text(base + f"\n\n✅ Saved: {fact}")
    else:  # dismiss
        await query.edit_message_text(base + "\n\n— okay, not saving that.")


@_allowed_only
async def on_track_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tap on '➕ Track this' / 'Dismiss' under a proactive notification."""
    query = update.callback_query
    await query.answer()

    action, _, token = (query.data or "").partition(":")
    pending: dict[str, dict] = context.application.bot_data.setdefault("pending_commitments", {})
    payload = pending.pop(token, None)
    base = query.message.text or ""

    if payload is None:
        await query.edit_message_text(base + "\n\n(that suggestion has expired)")
        return

    if action == "track":
        ledger: LedgerStore = context.application.bot_data["ledger"]
        # source-key dedup means tapping twice (or after the agent already tracked it)
        # won't create a duplicate.
        c = ledger.add(payload["text"], kind="reply", source=payload.get("source", ""))
        await query.edit_message_text(base + f"\n\n➕ Tracking ({c.id}): {c.text}")
    else:  # untrack / dismiss
        await query.edit_message_text(base + "\n\n— okay, not tracking that.")


@_allowed_only
async def on_reminder_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tap '✅ Done' under a proactive reminder / check-in — mark the commitment done."""
    query = update.callback_query
    await query.answer()
    _action, _, cid = (query.data or "").partition(":")
    ledger: LedgerStore = context.application.bot_data["ledger"]
    base = query.message.text or ""
    done = ledger.mark_done(cid)
    if done is None:
        await query.edit_message_text(base + "\n\n(couldn't find that one — maybe already cleared)")
    else:
        await query.edit_message_text(base + "\n\n✅ Marked done.")


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #


async def _on_startup(app: Application) -> None:
    config: Config = app.bot_data["config"]
    if config.notify_enabled and not app.bot_data["mail_accounts"].is_empty():
        start_notifier(app)
    else:
        logger.info("Notifier disabled (notify_enabled=%s).", config.notify_enabled)
    if config.brief_enabled or config.weekly_review_enabled or config.reminder_enabled:
        start_scheduler(app)
    else:
        logger.info("Scheduler disabled (brief + weekly review + reminders all off).")

    # If Gmail was set up (creds + token present) but didn't connect, the token has
    # almost certainly expired. Tell the user out loud instead of failing silently.
    accounts = app.bot_data["mail_accounts"]
    if (
        accounts.get("personal") is None
        and config.google_credentials_file.exists()
        and config.google_token_file.exists()
    ):
        try:
            await app.bot.send_message(
                chat_id=config.allowed_user_id,
                text=(
                    "⚠️ Heads up: my Gmail access isn't working right now — the login has "
                    "likely expired. Re-authorise on the laptop and redeploy the token when "
                    "you can. Your work email is unaffected."
                ),
            )
        except Exception:  # noqa: BLE001 - an alert failure must not block startup
            logger.exception("Failed to send Gmail-auth alert")


async def _on_shutdown(app: Application) -> None:
    stop_notifier(app)
    stop_scheduler(app)


def build_application(config: Config, llm: LLMClient, memory: MemoryStore | None = None) -> Application:
    """Assemble the Telegram application with handlers and shared state."""
    app = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )
    mem = memory or MemoryStore(config.data_dir)
    profile = ProfileStore(config.data_dir)
    accounts = build_mail_accounts(config)
    ledger = LedgerStore(config.data_dir)
    activity = ActivityLog(config.data_dir)

    app.bot_data["config"] = config
    app.bot_data["tz"] = resolve_tz(config.timezone)
    app.bot_data["llm"] = llm
    app.bot_data["memory"] = mem
    app.bot_data["profile"] = profile
    app.bot_data["mail_accounts"] = accounts
    app.bot_data["ledger"] = ledger
    app.bot_data["activity"] = activity
    app.bot_data["email_tools"] = (
        build_email_tools(accounts) + build_notify_tools(mem) + build_ledger_tools(ledger)
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("remember", remember))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("forget", forget))
    app.add_handler(CommandHandler("new", new_conversation))
    app.add_handler(CommandHandler("inbox", inbox))
    app.add_handler(CommandHandler("brief", brief_cmd))
    app.add_handler(CommandHandler(["agenda", "waiting"], agenda_cmd))
    app.add_handler(CommandHandler("track", track_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("onboard", onboard_cmd))
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CallbackQueryHandler(on_onboard_button, pattern=r"^onb:"))
    app.add_handler(CallbackQueryHandler(on_memory_button, pattern=r"^(remember|dismiss):"))
    app.add_handler(CallbackQueryHandler(on_track_button, pattern=r"^(track|untrack):"))
    app.add_handler(CallbackQueryHandler(on_reminder_done, pattern=r"^rdone:"))
    app.add_handler(CallbackQueryHandler(on_reply_action, pattern=r"^(send|savedraft|cancelreply):"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    # httpx logs every request URL at INFO — and the Telegram API URL embeds the
    # bot token. Silence it to WARNING so the token never lands in the journal/logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        config = Config.load(require_telegram=True)
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}")

    llm = DeepSeekClient.from_config(config)
    memory = MemoryStore(config.data_dir)
    app = build_application(config, llm, memory)
    accounts: MailAccounts = app.bot_data["mail_accounts"]

    logger.info(
        "Aurora bot starting (model=%s, autonomy=%s). user=%s. memory=%d entries. mail=%s",
        config.deepseek_model,
        config.autonomy_mode,
        config.allowed_user_id,
        len(memory.entries()),
        accounts.names() or "none",
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
