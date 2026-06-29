"""Telegram surface — M0 echo bot wired to the LLM.

This proves the surface + LLM plumbing end-to-end: a message in Telegram goes to
the LLM and the reply comes back. Access is restricted to the single allowed
user id from config — Aurora is a *personal* assistant, not a public bot.

Later milestones grow this file into the real review surface (digests, proposal
accept/edit/reject, the ``/mode`` command).
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from aurora.config import Config, ConfigError
from aurora.llm import DeepSeekClient, LLMClient, Message

logger = logging.getLogger("aurora.telegram")

# Aurora's voice for M0. Replaced by richer, rule-aware prompting in later
# milestones once memory/rules exist.
SYSTEM_PROMPT = (
    "You are Aurora, a calm, concise personal assistant. "
    "You help the user declutter their digital life and never let them miss a thing. "
    "For now you are in early setup (M0): you can just chat. "
    "Keep replies short and warm."
)


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
    user = update.effective_user
    await update.effective_message.reply_text(
        f"Hi {user.first_name} — Aurora here. I'm in early setup (M0); we can chat. "
        f"Your Telegram id is {user.id}."
    )


@_allowed_only
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handy for confirming the configured id matches you."""
    await update.effective_message.reply_text(f"Your Telegram user id is {update.effective_user.id}.")


@_allowed_only
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo-via-LLM: route the user's text through the LLM and reply."""
    llm: LLMClient = context.application.bot_data["llm"]
    text = update.effective_message.text or ""

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )
    try:
        reply = llm.complete(
            [Message("system", SYSTEM_PROMPT), Message("user", text)],
            temperature=0.7,
        )
    except Exception as exc:  # noqa: BLE001 - surface any LLM failure to the user
        logger.exception("LLM call failed")
        reply = f"Sorry — I couldn't reach my brain just now ({exc.__class__.__name__})."

    await update.effective_message.reply_text(reply)


def build_application(config: Config, llm: LLMClient) -> Application:
    """Assemble the Telegram application with handlers and shared state."""
    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["config"] = config
    app.bot_data["llm"] = llm

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whoami", whoami))
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
    app = build_application(config, llm)

    logger.info(
        "Aurora bot starting (model=%s, autonomy=%s). Allowed user id=%s.",
        config.deepseek_model,
        config.autonomy_mode,
        config.allowed_user_id,
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
