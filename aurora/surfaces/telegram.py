"""Telegram surface — chat wired to the LLM, grounded in persistent memory.

A message in Telegram goes to the LLM (with Aurora's memory injected) and the
reply comes back. Access is restricted to the single allowed user id from config
— Aurora is a *personal* assistant, not a public bot.

Memory is read/written via :class:`aurora.memory.MemoryStore`. Aurora *proposes*
to remember durable facts; it never stores silently (approve-before-acting).

Later milestones grow this file into the full review surface (digests, proposal
accept/edit/reject, the ``/mode`` command).
"""

from __future__ import annotations

import logging
import re

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

from aurora.config import Config, ConfigError
from aurora.llm import DeepSeekClient, LLMClient, Message
from aurora.memory import MemoryStore

logger = logging.getLogger("aurora.telegram")

# Aurora's base voice. The user's current memory is appended at call time via
# MemoryStore.render_for_prompt(), so replies are grounded in what Aurora knows.
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
    """Split an LLM reply into (visible_text, proposed_fact_or_None).

    Strips the ``[[REMEMBER: ...]]`` marker from what the user sees and returns the
    proposed fact separately so the caller can offer a button.
    """
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


@_allowed_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    memory: MemoryStore = context.application.bot_data["memory"]
    name = memory.display_name() or update.effective_user.first_name
    await update.effective_message.reply_text(
        f"Hi {name} — Aurora here. I remember what you tell me: "
        "/remember to teach me, /memory to see what I know, /forget to drop something."
    )


@_allowed_only
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handy for confirming the configured id matches you."""
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
    await update.effective_message.reply_text(
        "Here's what I remember:\n" + "\n".join(lines)
    )


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


def _stash_pending_fact(context: ContextTypes.DEFAULT_TYPE, fact: str) -> str:
    """Hold a proposed fact server-side (callback_data is too small for full text).

    Returns a short token to embed in the button's callback_data.
    """
    pending = context.application.bot_data.setdefault("pending_memories", {})
    seq = context.application.bot_data.get("pending_seq", 0) + 1
    context.application.bot_data["pending_seq"] = seq
    token = str(seq)
    pending[token] = fact
    return token


@_allowed_only
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route the user's text through the LLM, grounded in memory + recent conversation."""
    llm: LLMClient = context.application.bot_data["llm"]
    memory: MemoryStore = context.application.bot_data["memory"]
    text = update.effective_message.text or ""

    # Short-term memory: the recent back-and-forth, so Aurora can follow a thread
    # (e.g. answer "what's your name?" → "Aji" and connect the two). Persists for
    # the bot's lifetime, per chat; long-term facts are saved separately.
    history: list[Message] = context.chat_data.setdefault("history", [])
    history.append(Message("user", text))

    system_prompt = SYSTEM_PROMPT + memory.render_for_prompt()
    messages = [Message("system", system_prompt), *history[-MAX_HISTORY_MESSAGES:]]

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )
    try:
        raw = llm.complete(messages, temperature=0.7)
    except Exception as exc:  # noqa: BLE001 - surface any LLM failure to the user
        logger.exception("LLM call failed")
        history.pop()  # don't keep a turn we never answered
        await update.effective_message.reply_text(
            f"Sorry — I couldn't reach my brain just now ({exc.__class__.__name__})."
        )
        return

    visible, fact = parse_remember_marker(raw)
    if not visible:
        visible = "Want me to remember that?"

    # Record Aurora's (clean) reply so the next turn has the full thread.
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
async def on_memory_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle taps on the Remember / Dismiss buttons."""
    query = update.callback_query
    await query.answer()  # stop Telegram's loading spinner

    action, _, token = (query.data or "").partition(":")
    pending: dict[str, str] = context.application.bot_data.setdefault("pending_memories", {})
    fact = pending.pop(token, None)
    base = query.message.text or ""

    if fact is None:
        # Bot restarted or already handled — the proposal is gone.
        await query.edit_message_text(base + "\n\n(that suggestion has expired)")
        return

    if action == "remember":
        memory: MemoryStore = context.application.bot_data["memory"]
        memory.add(fact)
        await query.edit_message_text(base + f"\n\n✅ Saved: {fact}")
    else:  # dismiss
        await query.edit_message_text(base + "\n\n— okay, not saving that.")


def build_application(config: Config, llm: LLMClient, memory: MemoryStore | None = None) -> Application:
    """Assemble the Telegram application with handlers and shared state."""
    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["config"] = config
    app.bot_data["llm"] = llm
    app.bot_data["memory"] = memory or MemoryStore(config.data_dir)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("remember", remember))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("forget", forget))
    app.add_handler(CommandHandler("new", new_conversation))
    app.add_handler(CallbackQueryHandler(on_memory_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        config = Config.load(require_telegram=True)
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}")

    llm = DeepSeekClient.from_config(config)
    memory = MemoryStore(config.data_dir)
    app = build_application(config, llm, memory)

    logger.info(
        "Aurora bot starting (model=%s, autonomy=%s). Allowed user id=%s. Memory: %s (%d entries).",
        config.deepseek_model,
        config.autonomy_mode,
        config.allowed_user_id,
        memory.path,
        len(memory.entries()),
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
