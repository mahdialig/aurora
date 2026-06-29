# Aurora — Project State

> **This is the session entry point.** When the user says "Start" / "Start session",
> read this file first, then `WORKLOG.md`, `DECISIONS.md`, and `BACKLOG.md` in this
> folder, then give a 4–6 line recap and ask what to work on. Keep this file current
> at the end of each working session.

_Last updated: 2026-06-29 (end of session 5)._

## One-line status
Aurora is a Telegram-based conversational AI assistant that can read, search, and reply
to the user's **personal Gmail** (with approval). Built through M1; next up is the **work
IMAP account**, then **proactive notifications**.

## What Aurora is
A personal assistant the user *delegates to* (not a dashboard). The user talks to her in
Telegram; she uses tools (currently email) to act, and reports in her own words. See
`DECISIONS.md` for the product principles.

## Where we are
- **M0 — Scaffolding** ✅ (commit `9e15fdd`): Telegram bot + swappable LLM client (DeepSeek) + config/secrets.
- **Memory slice** ✅ (commit `6078923`): persistent long-term memory (`data/memory/memory.md`),
  `/remember` `/memory` `/forget` `/new`, propose-to-remember buttons, short-term conversation thread.
- **M1 — Conversational email agent (Gmail)** ✅ (commit `f2df943`):
  - Stage 1: `LLMClient.chat()` with OpenAI-style function calling.
  - Stage 2: `MailAccount` interface + Gmail connector + registry.
  - Stage 3: agent loop + read tools (`list_unread`, `search_mail`, `read_email`).
  - Stage 4: action tools (`reply_to_email`, `resend_last_draft`) with Send/Save-draft/Cancel approval.
  - Fixes: spam/trash search, no agent dead-ends, forgotten preferences truly revert.
- **Next: M2 — Work IMAP account** (see BACKLOG), then proactive notifications.

## Live runtime (current)
- The bot runs on **this laptop** via `python -m aurora.surfaces.telegram` (a long-running
  background process during sessions). It is NOT yet deployed to the VPS.
- Telegram bot: **@paagentaurorabot**, locked to the user's Telegram id `6959305748`.
- Model: `deepseek-v4-flash`. Autonomy mode: `approve_all` (sending always needs a tap).
- Connected mailbox: **personal Gmail** `magyp.magyp@gmail.com` (OAuth, scope `gmail.modify`).
  Google Cloud project: `aurora-500907` (OAuth app in "Testing" → token may expire ~weekly).

## How to resume a working session
1. Read this file + `WORKLOG.md` + `DECISIONS.md` + `BACKLOG.md`.
2. Verify health: `cd` to repo, run `./.venv/Scripts/python.exe -m pytest -q` (expect all green)
   and `./.venv/Scripts/ruff.exe check aurora tests`.
3. If you need the bot live: start it (see `../CLAUDE.md` Commands). `.env`, `credentials.json`,
   `data/token.json` already exist locally (all gitignored) — don't recreate them.
4. Pick the top BACKLOG item (or whatever the user asks) and go.

## Key facts a new session must not re-derive
- Accounts: personal = Gmail (API/OAuth); work = `mahdi.ali@matajari.co.id` on dapurhosting →
  **IMAP/SMTP, NOT Google** (not connected yet; needs mailbox password in `.env`).
- Aurora must never dump the inbox verbatim — she's a delegate, not a viewer.
- Anything that leaves a mailbox (send) is approval-gated regardless of autonomy mode.
- Secrets live only in gitignored files; never commit them.
