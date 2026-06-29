"""Telegram surface — Aurora as a conversational agent.

A message goes to the agent loop (LLM + memory + tools). Aurora may use tools
(e.g. read/search email across the connected accounts) to answer, and reports in
her own words — she is a delegate, not a viewer. Actions that leave a mailbox are
approval-gated (added in stage 4). Access is restricted to the single allowed user.
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

from aurora.agent import run_agent
from aurora.config import Config, ConfigError
from aurora.llm import DeepSeekClient, LLMClient, Message
from aurora.memory import MemoryStore
from aurora.sources.base import Reply
from aurora.sources.registry import MailAccounts, build_mail_accounts
from aurora.tools.email_tools import build_email_tools

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
    name = memory.display_name() or update.effective_user.first_name
    await update.effective_message.reply_text(
        f"Hi {name} — Aurora here. Just talk to me: ask what's new in your email, ask me to "
        "reply to someone, or tell me things to remember. /memory shows what I know."
    )


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
        "(read the email first). To re-send a reply you already drafted in this conversation, "
        "call resend_last_draft. NEVER write the reply text directly in chat or ask 'send it?' "
        "in words — those tools are the ONLY way the user can act (they show Send / Save-draft / "
        "Cancel buttons). "
        "Keep email replies CONCISE by default. Follow only the user's CURRENT preferences (in "
        "MEMORY below) and their latest instruction for length and tone — do NOT copy the length "
        "or verbosity of your earlier drafts in this conversation."
    )


async def _respond(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str) -> None:
    """Core turn: run the agent loop (memory + email tools) and reply."""
    llm: LLMClient = context.application.bot_data["llm"]
    memory: MemoryStore = context.application.bot_data["memory"]
    accounts: MailAccounts = context.application.bot_data["mail_accounts"]
    tools = context.application.bot_data["email_tools"]

    history: list[Message] = context.chat_data.setdefault("history", [])
    history.append(Message("user", user_text))

    system_prompt = SYSTEM_PROMPT + _email_capability(accounts) + memory.render_for_prompt()
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

    try:
        if action == "send":
            account.send_reply(reply)
            await query.edit_message_text(base + "\n\n✅ Sent.")
        else:  # savedraft
            account.create_draft(reply)
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


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #


def build_application(config: Config, llm: LLMClient, memory: MemoryStore | None = None) -> Application:
    """Assemble the Telegram application with handlers and shared state."""
    app = Application.builder().token(config.telegram_bot_token).build()
    mem = memory or MemoryStore(config.data_dir)
    accounts = build_mail_accounts(config)

    app.bot_data["config"] = config
    app.bot_data["llm"] = llm
    app.bot_data["memory"] = mem
    app.bot_data["mail_accounts"] = accounts
    app.bot_data["email_tools"] = build_email_tools(accounts)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("remember", remember))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("forget", forget))
    app.add_handler(CommandHandler("new", new_conversation))
    app.add_handler(CommandHandler("inbox", inbox))
    app.add_handler(CallbackQueryHandler(on_memory_button, pattern=r"^(remember|dismiss):"))
    app.add_handler(CallbackQueryHandler(on_reply_action, pattern=r"^(send|savedraft|cancelreply):"))
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
