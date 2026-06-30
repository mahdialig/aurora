# Aurora — Project State

> **This is the session entry point.** When the user says "Start" / "Start session",
> read this file first, then `WORKLOG.md`, `DECISIONS.md`, and `BACKLOG.md` in this
> folder, then give a 4–6 line recap and ask what to work on. Keep this file current
> at the end of each working session.

_Last updated: 2026-06-30 (end of session 8)._

## One-line status
Aurora is a Telegram-based conversational AI assistant that reads, searches, replies to, and
**composes** mail across the user's **personal Gmail** and **work email** (dapurhosting
IMAP/SMTP), **proactively notifies** about new mail that matters, and now tracks **open
commitments** + sends a **daily brief / weekly review** so nothing slips — learning the user's
preferences over time. Built through M4.

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
- **M2 — Work IMAP/SMTP account** ✅ (session 6): `aurora/sources/imap.py`
  `ImapAccount(MailAccount)` over `imaplib`/`smtplib` — read/search (INBOX+Junk), draft via
  IMAP APPEND, send via SMTP + a copy filed to Sent. Shared `strip_html` helper promoted to
  `base.py`. Config gained `work_*` fields; registry wires `accounts["work"]`. Verified live
  end-to-end through the bot (read + draft round-trip + real SMTP send + Sent copy). Fixed a
  folder-resolution bug found in testing (Dovecot returns bare LIST names, not quoted). Also added
  a FIDELITY prompt clause (D12) after Aurora altered an emoji in a send-confirmation read-back.
- **M3 — Compose + proactive notifications** ✅ (session 7):
  - **Compose**: `compose_email` action tool (new email, not a reply) reusing the Send/Save-draft/
    Cancel flow; Gmail send/draft now omit an empty `threadId`.
  - **Proactive notifications** (`aurora/notify/`): a dependency-free asyncio poller (`job.py`,
    started in PTB `post_init`) scans unread every `AURORA_NOTIFY_INTERVAL_SECONDS` (default 600),
    diffs against `NotifyState` (`state.py`, restart-safe JSON, seeds silently on first contact),
    and a batched LLM `classifier.py` decides notify/ask/skip (smart-filter + ask posture). Learns
    via `set_notification_rule` (`notify_tools.py`) → memory; reactions resolve through a RECENT
    NOTIFICATIONS prompt block. Realizes **D9**; see D13.
  - Verified live: `poll_once` against the real mailbox classified actual mail sensibly (money/people
    → notify; release/maintenance notices → ask). 86 tests pass.
- **M4 — Don't-miss-a-thing engine** ✅ (session 8): the "never miss a thing" substrate.
  - **Commitments ledger** (`aurora/ledger/`): hand-editable `data/ledger/commitments.md` tracking
    tasks/replies/deadlines/meeting-prep with owner/status/due/provenance; atomic+locked writes.
    Inline tools `add/list/update/mark_done` (`aurora/tools/ledger_tools.py`); open items injected
    into the prompt each turn. Commands `/agenda` (`/waiting`), `/track`, `/done`.
  - **Daily brief + weekly review** (`aurora/brief/`, `aurora/schedule/`): a dependency-free
    scheduler (60s tick + persisted last-fired, offline-catch-up + DST-safe via `tzdata`) composes a
    structured EA-style brief (one `llm.complete`, quiet-day path) from the ledger + a small activity
    log (`aurora/activity/`). `/brief` on demand. Config: `AURORA_TIMEZONE`/`AURORA_BRIEF_*`/
    `AURORA_WEEKLY_REVIEW_*`.
  - **Email auto-capture**: the notify classifier now also suggests a `commitment`; notifications get
    a one-tap "➕ Track this" button (deduped by `email:<account>:<id>`). See D14–D17.
  - **127 tests pass; ruff clean.** Unit + import verified; not yet driven live through the bot.
- **Next: VPS deployment** so notifications + the daily brief run 24/7 (currently laptop-only); then
  the self-learning upgrade (onboarding + reflection, D17); then calendar.

## Live runtime (current)
- The bot runs on **this laptop** via `python -m aurora.surfaces.telegram` (a long-running
  background process during sessions). It is NOT yet deployed to the VPS.
- Telegram bot: **@paagentaurorabot**, locked to the user's Telegram id `6959305748`.
- Model: `deepseek-v4-flash`. Autonomy mode: `approve_all` (sending always needs a tap).
- Proactive notifications: ON (`AURORA_NOTIFY_ENABLED`, default true), checks every 600s
  (`AURORA_NOTIFY_INTERVAL_SECONDS`). Seen-mail state persists in `data/notify_state.json`.
  Only runs while the bot is running (laptop) → another reason to deploy to the VPS.
- Connected mailboxes:
  - **personal Gmail** `magyp.magyp@gmail.com` (OAuth, scope `gmail.modify`). Google Cloud
    project: `aurora-500907` (OAuth app in "Testing" → token may expire ~weekly).
  - **work email** `mahdi.ali@matajari.co.id` on dapurhosting (IMAP/SMTP `d001.dapurhosting.com`,
    993/465 SSL). Creds in `.env` (`WORK_EMAIL`/`WORK_PASSWORD`); both gitignored.

## How to resume a working session
1. Read this file + `WORKLOG.md` + `DECISIONS.md` + `BACKLOG.md`.
2. Verify health: `cd` to repo, run `./.venv/Scripts/python.exe -m pytest -q` (expect all green)
   and `./.venv/Scripts/ruff.exe check aurora tests`.
3. If you need the bot live: start it (see `../CLAUDE.md` Commands). `.env`, `credentials.json`,
   `data/token.json` already exist locally (all gitignored) — don't recreate them.
4. Pick the top BACKLOG item (or whatever the user asks) and go.

## Key facts a new session must not re-derive
- Accounts: personal = Gmail (API/OAuth); work = `mahdi.ali@matajari.co.id` on dapurhosting →
  **IMAP/SMTP, NOT Google** (now connected; password in `.env`). Username = full email address.
- Aurora must never dump the inbox verbatim — she's a delegate, not a viewer.
- Anything that leaves a mailbox (send) is approval-gated regardless of autonomy mode.
- Secrets live only in gitignored files; never commit them.
